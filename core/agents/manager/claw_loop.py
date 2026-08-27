"""
Manager Agent — CLAW 直通模式（單迴圈）

Hermes-agent / OpenClaw 式的單一 tool-calling 迴圈：
query → CryptoMind ReAct loop → 最終回覆。

取代 5 節點管線（intent 分解 / aggregate / reflect / synthesize）的關鍵差異：
- 寫最終答案的模型與看到工具原始輸出的模型是**同一個 context**，
  結構性消除「合成層看不到工具輸出而腦補」的幻覺來源。
- 一個問題只有一條 LLM 迴圈（原本 5-8 次呼叫），大幅減少免費層 429。
- token 直接從迴圈收尾訊息串流給前端，事件格式與舊管線相容。

以 CLAW_DIRECT_MODE 環境變數控制（預設開啟），設 false 可退回舊管線。
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from langgraph.errors import GraphInterrupt

from api.utils import logger, run_sync
from core.agents.models import SubTask
from core.agents.prompt_guard import sanitize_user_input

# ──────────────────────────────────────────────────────────────────────────────
# Hermes-style error classification: 暫時性錯誤（rate limit 429 / 供應商 5xx）
# 才 retry-once。其他錯誤（401/403/402）直接 fail-fast 走友善訊息，避免把
# 額度浪費在必然失敗的重試上。對齊 hermes-agent 的 classify_api_error() 概念。
#
# 分類邏輯（含 NVIDIA NIM 的 ResourceExhausted / 供應商 5xx InternalServerError）
# 已抽到 ``core.agents.rate_limit`` 給 base_react_agent 與本模組共用。
# ──────────────────────────────────────────────────────────────────────────────
from core.agents.rate_limit import is_transient_error as _is_transient
from core.agents.rate_limit import is_worker_overload_error as _is_worker_overload

from .mixin_base import ManagerAgentMixin

# ──────────────────────────────────────────────────────────────────────────────
# Consent Gate 意圖過濾（避免過度觸發）
# ──────────────────────────────────────────────────────────────────────────────
# 原本 consent gate 掃「整個工具池」，只要池裡有 high-risk tool（如 KYC）就彈同意，
# 導致「問比特幣價格」也彈 KYC consent。這裡依 query 意圖過濾：只有當 query
# 真的可能用到該 high-risk tool 時，才把它納入掃描池。純查詢（價格/新聞/分析）
# 不觸發 consent；真正要動錢（查錢包餘額/KYC/交易記錄）才彈。
_HIGH_RISK_INTENT_PATTERNS: Dict[str, re.Pattern] = {
    # 查 ETH 資產：只認明確的 ETH 訊號（0x 地址 / eth 字樣）。
    # 注意：「錢包.*餘額 / wallet.*balance」不能綁在這裡——平台是 TON 生態，
    # 「查我錢包餘額」對應的是 get_ton_balance（low risk，不需 consent）。
    # 綁在 ETH 上會導致 TON 使用者查自己錢包時誤彈「輸入 0x ETH 地址」的 consent。
    "get_eth_balance": re.compile(
        r"0x[0-9a-fA-F]{6,}|eth\s*(餘額|余额|balance)|ethereum\s*(餘額|余额|balance)",
        re.IGNORECASE,
    ),
    "get_erc20_token_balance": re.compile(
        r"erc20.*(餘額|余额|balance)|代幣.*(餘額|余额|balance)|token.*(balance)",
        re.IGNORECASE,
    ),
    # 查交易記錄 / 資金流向
    "get_address_transactions": re.compile(
        r"(交易|transaction).*(記錄|记录|history|歷史|历史)|資金流向|资金流向|"
        r"(轉帳|转账|transfer).*(記錄|记录|history)|0x[0-9a-fA-F]{6,}",
        re.IGNORECASE,
    ),
    # 鯨魚 / 大額轉帳
    "get_whale_alerts": re.compile(
        r"(鯨魚|鲸鱼|whale|巨鯨|巨鲸)|(大額|大额|large).*(轉帳|转账|transfer|move)",
        re.IGNORECASE,
    ),
    # KYC / 開戶 / 申請
    "submit_kyc_application": re.compile(
        r"(kyc|開戶|开户|open\s*account)|(申請|申请|apply|submit).*(開戶|开户|account|kyc)",
        re.IGNORECASE,
    ),
}


def _filter_high_risk_by_intent(
    high_risk_tools: list, query: str
) -> list:
    """依 query 意圖過濾 high-risk tool，只保留 query 可能用到的。

    純查詢（價格/新聞/技術分析）不匹配任何模式 → 回空 → 不彈 consent。
    query 涉及錢包/KYC/交易 → 保留對應 tool → 正常彈 consent。
    已 granted（consent_granted=True）的情境由呼叫端短路，不進這裡。
    """
    if not high_risk_tools or not query:
        return []
    q = query.lower()
    kept = []
    for tool in high_risk_tools:
        name = tool.get("name", "") if isinstance(tool, dict) else getattr(tool, "name", "")
        pattern = _HIGH_RISK_INTENT_PATTERNS.get(name)
        if pattern and pattern.search(q):
            kept.append(tool)
    return kept

# ── Phase D：詐騙判定證據鏈（Trustworthy AI HITL 場景 B 輕量版）──
# 偵測 AI 是否用了 GoPlus 詐騙判定工具；若是，從 process-level stash 取 raw
# info 組結構化證據。完全不用 LangGraph interrupt，靠後端附加。
# 路線 B 新增 assess_jetton_safety（TON 詐騙檢測，與 GoPlus 對稱）。
_SECURITY_TOOLS = {"check_token_security", "check_address_safety", "assess_jetton_safety"}
# 只在這些 verdict 顯示證據卡片（normal/insufficient 不顯示）
_SCAM_EVIDENCE_VERDICTS = {"high_risk", "trusted_with_permissions", "warning"}


def _build_scam_evidence(used_tools) -> Optional[dict]:
    """若這輪用了詐騙判定工具（GoPlus EVM / TON TonAPI），組結構化證據鏈；否則回 None。

    證據由後端從 raw info 萃取（_extract_risk_signals / _extract_ton_signals
    + risk_scoring），不依賴 LLM 文字、不改 LLM 看到的工具 markdown 輸出。
    """
    if not used_tools or not (set(used_tools) & _SECURITY_TOOLS):
        return None
    try:
        from ..risk_scoring import score_scam_confidence

        # ── EVM 路徑（GoPlus）──
        if set(used_tools) & {"check_token_security", "check_address_safety"}:
            from core.tools.crypto_modules.goplus import (
                _extract_risk_signals,
                pop_token_security_raw,
            )

            stashed = pop_token_security_raw()
            if stashed:
                last = stashed[-1]
                signals = _extract_risk_signals(last["info"])
                if signals.get("verdict") in _SCAM_EVIDENCE_VERDICTS:
                    scoring = score_scam_confidence(signals)
                    return {
                        "verdict": scoring["verdict"],
                        "confidence": scoring["confidence"],
                        "breakdown": scoring["breakdown"],
                        "signals": signals,
                        "target": last.get("contract_address"),
                        "chain_id": last.get("chain_id"),
                        "requires_ack": True,
                    }

        # ── TON 路徑（TonAPI，路線 B 新增）──
        if "assess_jetton_safety" in used_tools:
            from core.tools.crypto_modules.ton_safety import (
                _extract_ton_signals,
                pop_ton_safety_raw,
            )

            stashed = pop_ton_safety_raw()
            if stashed:
                last = stashed[-1]
                signals = _extract_ton_signals(last["safety"])
                if signals.get("verdict") in _SCAM_EVIDENCE_VERDICTS:
                    scoring = score_scam_confidence(signals)
                    return {
                        "verdict": scoring["verdict"],
                        "confidence": scoring["confidence"],
                        "breakdown": scoring["breakdown"],
                        "signals": signals,
                        "target": last.get("address"),
                        "chain_id": "ton",
                        "requires_ack": True,
                    }

        return None
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("[ClawLoop] scam evidence build failed: %s", exc)
        return None


def _extract_clarify_signal(result_data: dict) -> Optional[dict]:
    """Phase F：從 result.data 抽出 clarify 工具的釐清訊號。

    Hermes 式 model-driven 釐清的訊號傳遞：模型呼叫 clarify 工具 → 工具回傳
    `{"__needs_clarify__": True, "question": ..., "options": [...]}` JSON →
    該字串進 result.data["tool_outputs"]（既有收集機制）。本函式掃 tool_outputs
    找標記，解析回 dict 供 node-level interrupt 使用。

    Args:
        result_data: AgentResult.data dict（含 used_tools、tool_outputs、finish_reason）。

    Returns:
        {"question": str, "options": list} 或 None（沒有 clarify 訊號）。
    """
    if not isinstance(result_data, dict):
        return None
    tool_outputs = result_data.get("tool_outputs", []) or []
    if not tool_outputs:
        return None
    try:
        from core.tools.clarify_tool import parse_clarify_signal

        for output in tool_outputs:
            if not isinstance(output, str):
                continue
            signal = parse_clarify_signal(output)
            if signal:
                return {
                    "question": signal.get("question", ""),
                    "options": signal.get("options", []) or [],
                }
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.debug("[ClawLoop] clarify signal extract failed: %s", exc)
    return None


def _extract_consent_signal(result_data: dict) -> Optional[dict]:
    """從 result.data 抽出 skill/memory 工具的 ``__needs_consent__`` marker。

    工具（remember / propose_custom_skill）不直接寫 DB，只回傳 marker JSON。
    本函式掃 tool_outputs 找標記（仿 _extract_clarify_signal）。

    Returns:
        marker dict（含 kind/content 或 skill 欄位）或 None（沒有 clarify 訊號）。
    """
    signals = _extract_consent_signals(result_data)
    return signals[0] if signals else None


def _extract_consent_signals(result_data: dict) -> list:
    """抽出**全部** ``__needs_consent__`` marker（多卡批次同意用）。

    一輪 agent 可能同時提案多個動作（記帳＋刪記憶＋增記憶…）。舊版只取
    第一個 marker → 只彈一張卡、其餘提案靜默丟失（2026-08-25 線上回報）。
    """
    if not isinstance(result_data, dict):
        return []
    tool_outputs = result_data.get("tool_outputs", []) or []
    if not tool_outputs:
        return []
    found = []
    for output in tool_outputs:
        if not isinstance(output, str):
            continue
        stripped = output.strip()
        if not stripped.startswith("{"):
            continue
        try:
            parsed = json.loads(stripped)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict) and parsed.get("__needs_consent__") is True:
            found.append(parsed)
    return found


def _consent_identity(marker: dict) -> str:
    """marker 的穩定 identity——與 ts 無關（resume 重跑時工具會帶新 ts 重新提案）。

    - journal_entry：proposal_id（record_entry 產生的內容雜湊）
    - journal_delete / journal_update：kind + entry_id（+updates）
    - create/delete_memory：kind + key
    - 其他（custom_skill 等舊 marker）：整包內容去 ts 後的雜湊
    """
    import hashlib

    kind = str(marker.get("kind", ""))
    if kind == "journal_entry" and marker.get("proposal_id"):
        return f"journal_entry:{marker['proposal_id']}"
    if kind in ("journal_delete", "journal_update"):
        base = f"{kind}:{marker.get('entry_id')}"
        if kind == "journal_update":
            import json as _json

            base += ":" + _json.dumps(marker.get("updates") or {}, sort_keys=True, ensure_ascii=False)
        return base
    if marker.get("key"):
        return f"{kind}:{marker['key']}"
    payload = {k: v for k, v in marker.items() if k not in ("ts",)}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:12]
    return f"{kind or 'consent'}:{digest}"


# 可用既有「單卡」豐富 UI 的 kind（金流記帳/記憶/skill）。journal_delete /
# journal_update 走 multi_consent 批次渲染器（單筆也適用），不動既有卡片。
_SINGLE_CARD_KINDS = {
    "journal_entry",
    "create_memory",
    "delete_memory",
    "custom_skill",
}


def build_multi_consent_payload(signals: list, language: str) -> dict:
    """把多個 pending 提案包成一張 multi_consent 卡（一次 interrupt、一次 resume）。"""
    from core.agents.manager.consent_gate import (
        build_multi_consent_cards,
        build_multi_consent_message,
    )

    return {
        "type": "multi_consent",
        "message": build_multi_consent_message(len(signals), language),
        "cards": build_multi_consent_cards(signals, language),
    }


def parse_multi_consent_answers(raw: Any, expected: int) -> list:
    """解析 multi_consent 的答案（前端 resume_answer 以 JSON 字串送回陣列）。

    每張卡的答案可以是 ``{action: 'approve'/'deny', edited_fields?}``（multi
    卡按鈕）或既有單卡的任何格式（向下相容）。fail-closed：長度不符補 deny、
    壞輸入全數 deny——絕不誤核可。
    """
    from core.agents.manager.consent_gate import parse_skill_memory_consent_answer

    answers: list = []
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("["):
            try:
                raw = json.loads(stripped)
            except (ValueError, TypeError):
                raw = None
    if isinstance(raw, list):
        answers = raw
    elif raw is not None:
        answers = [raw]

    def _normalize(item: Any) -> Any:
        # multi 卡按鈕送 action: approve/deny（無 approved 鍵）——先轉成
        # 共用 parser 認得的形狀
        if isinstance(item, dict) and item.get("action") in (
            "approve",
            "deny",
            "approve_all",
            "deny_all",
        ):
            return {
                "approved": str(item.get("action", "")).startswith("approve"),
                "edited_fields": item.get("edited_fields") or {},
            }
        return item

    parsed = [
        parse_skill_memory_consent_answer(_normalize(a))
        for a in answers[:expected]
    ]
    while len(parsed) < expected:
        parsed.append({"approved": False, "edited_fields": {}, "raw": None})
    return parsed


def _apply_consent_write(
    user_id: Optional[str], signal: dict, edited: dict
) -> Optional[int]:
    """核可後實際寫入——依 marker kind 呼叫對應 Store。

    安全不變量：user_id 來自 node 的 self.user_id（JWT/session），**不**從
    signal 讀——prompt injection 無法跨帳號寫入。edited 是使用者「先編輯再核可」
    覆蓋的欄位（可能為空）。

    Returns: journal_entry 時回寫入的 DB id（供 audit），其他 kind 回 None。

    kind: 'create_memory' → MemoryStore.write_facts;
          'delete_memory' → MemoryStore.delete_fact;
          'custom_skill'  → SkillPreferenceStore create/update/delete;
          'journal_entry' → TradeJournalRepo.add_entry（金流 HITL）。
    """
    if not user_id:
        logger.warning("[ClawLoop] consent write skipped: no user_id")
        return
    kind = signal.get("kind", "")
    try:
        if kind == "delete_memory":
            from core.database.memory import MemoryStore

            key = signal.get("key") or edited.get("key")
            if not key:
                logger.warning("[ClawLoop] memory delete skipped: no key")
                return
            MemoryStore(user_id=user_id).delete_fact(key)
            logger.info(
                "[ClawLoop] memory deleted (consented) user=%s key=%s",
                user_id, key,
            )
        elif kind in ("journal_delete", "journal_update"):
            # 帳本單筆刪改（2026-08-25；與 Web UI 同一個 repo 路徑：soft delete /
            # 匯率重算 update）。刪改前快照在 marker 的 before（audit 已記錄）。
            from core.orm.trade_journal_repo import get_journal_repo

            entry_id = signal.get("entry_id")
            if entry_id is None:
                logger.warning("[ClawLoop] journal %s skipped: no entry_id", kind)
                return None
            repo = get_journal_repo(user_id)
            if kind == "journal_delete":
                result = repo.delete_trade(int(entry_id), source="chat")
            else:
                updates = dict(signal.get("updates") or {})
                for field in ("currency", "category", "note"):
                    if edited.get(field) is not None:
                        updates[field] = edited[field]
                if edited.get("amount") is not None:
                    # 卡片編輯欄位是前端 JSON——數值防禦性轉型（journal_entry
                    # 分支同款）；非正數回退原提案（帳本金額必須 > 0）
                    try:
                        amt = float(edited["amount"])
                    except (TypeError, ValueError):
                        amt = None
                    updates["amount"] = amt if amt and amt > 0 else signal.get("amount")
                result = repo.update_entry(int(entry_id), source="chat", **updates)
            if result.get("ok"):
                logger.info(
                    "[ClawLoop] journal %s applied (consented) user=%s id=%s",
                    kind, user_id, entry_id,
                )
                return int(entry_id)
            logger.warning(
                "[ClawLoop] journal %s failed (consented) user=%s id=%s: %s",
                kind, user_id, entry_id, result.get("error"),
            )
            return None
        elif kind == "journal_entry":
            # 金流 HITL：核准後才寫入統一帳本。使用者可在卡上編輯
            # amount/currency/category/note；動過金額或幣別就放棄提案時
            # 凍結的匯率（改由 repo 以核可當下匯率重算），其餘沿用凍結值。
            from core.orm.trade_journal_repo import get_journal_repo

            # edited_fields 從前端 JSON 來，數值防禦性轉型（壞值回退原提案）
            try:
                amount = float(edited.get("amount", signal.get("amount", 0)))
            except (TypeError, ValueError):
                amount = float(signal.get("amount", 0))
            currency = str(
                edited.get("currency", signal.get("currency", "TWD"))
            ).strip().upper() or "TWD"
            rate_frozen = (
                amount == float(signal.get("amount", 0))
                and currency == str(signal.get("currency", "TWD")).strip().upper()
            )
            result = get_journal_repo(user_id).add_entry(
                entry_type=signal.get("entry_type", "expense"),
                symbol=signal.get("symbol", ""),
                market=signal.get("market", ""),
                side=signal.get("side", "buy"),
                quantity=signal.get("quantity", 1),
                price=amount,
                currency=currency,
                fee=signal.get("fee", 0),
                instrument_type=signal.get("instrument_type", "spot"),
                direction=signal.get("direction", "long"),
                leverage=signal.get("leverage", 1),
                category=edited.get("category", signal.get("category", "")),
                converted_amount=(
                    signal.get("converted_amount") if rate_frozen else None
                ),
                exchange_rate=signal.get("exchange_rate") if rate_frozen else None,
                # 凍結匯率是「對提案當下的基準幣」——基準幣必須一起帶，
                # 否則會把對 TWD 凍結的匯率存成 USD 基準（c039）
                base_currency=(
                    signal.get("base_currency") if rate_frozen else ""
                ),
                # 使用者在對話裡自己講的匯率要標 manual，不能混進 frozen
                rate_source=(
                    (signal.get("rate_source") or "frozen") if rate_frozen else "auto"
                ),
                note=edited.get("note", signal.get("note", "")),
                source="chat",
            )
            if result.get("ok"):
                logger.info(
                    "[ClawLoop] journal entry written (consented) user=%s id=%s "
                    "type=%s amount=%s %s",
                    user_id, result.get("id"), signal.get("entry_type"),
                    amount, currency,
                )
                return int(result.get("id"))
            logger.warning(
                "[ClawLoop] journal entry write failed (consented) user=%s: %s",
                user_id, result.get("error"),
            )
            return None
        elif kind == "create_memory":
            from core.database.memory import MemoryStore

            content = edited.get("content", signal.get("content", ""))
            category = edited.get("category", signal.get("category", "fact"))
            key = signal.get("key") or edited.get("key")
            if not key:
                from core.tools.remember_tool import _make_key

                key = _make_key(content, category)
            MemoryStore(user_id=user_id).write_facts([{
                "key": key,
                "value": content.strip(),
                "confidence": "high",
                "source_turn": None,
                "category": category,
            }])
            logger.info(
                "[ClawLoop] memory written (consented) user=%s category=%s",
                user_id, category,
            )
        elif kind == "custom_skill":
            from core.database.skill_preferences import SkillPreferenceStore

            store = SkillPreferenceStore(user_id=user_id)
            mode = signal.get("mode", "create")
            name = edited.get("skill_name", signal.get("skill_name", ""))
            if mode == "delete":
                store.delete_custom_skill(name)
                logger.info(
                    "[ClawLoop] skill deleted (consented) user=%s name=%s",
                    user_id, name,
                )
            elif mode == "update":
                store.update_custom_skill(
                    skill_name=name,
                    description=edited.get("description", signal.get("description", "")),
                    trigger_keywords=edited.get(
                        "trigger_keywords", signal.get("trigger_keywords", "")
                    ),
                    body=edited.get("body", signal.get("body", "")),
                    is_enabled=True,
                )
                logger.info(
                    "[ClawLoop] skill updated (consented) user=%s name=%s",
                    user_id, name,
                )
            else:  # create
                store.create_custom_skill(
                    skill_name=name,
                    description=edited.get("description", signal.get("description", "")),
                    trigger_keywords=edited.get(
                        "trigger_keywords", signal.get("trigger_keywords", "")
                    ),
                    body=edited.get("body", signal.get("body", "")),
                )
                logger.info(
                    "[ClawLoop] skill created (consented) user=%s name=%s",
                    user_id, name,
                )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        # 寫入失敗不該讓整個 turn 崩——記 log，agent 回應仍回。
        logger.warning("[ClawLoop] consent write failed (kind=%s): %s", kind, exc)


# agent 成功跑完但回應清洗後為空（例如只有工具結果、無結論文字）時的兜底訊息。
# 語言清單對齊前端 web/js/i18n.js 與 base_react_agent.empty_response_message。
_NO_VALID_RESULT_MESSAGES: dict[str, str] = {
    "zh-TW": "執行完成，但沒有有效結果。請嘗試更具體的問題。",
    "zh-CN": "执行完成，但没有有效结果。请尝试更具体的问题。",
    "en": "Execution finished, but no valid result was produced. Please try a more specific question.",
    "ru": "Выполнение завершено, но нет результата. Задайте более конкретный вопрос.",
}


def _no_valid_result_message(language: str) -> str:
    """清洗後回應為空時的在地化兜底訊息。未支援的 language code 落回英文。"""
    return _NO_VALID_RESULT_MESSAGES.get(
        language, _NO_VALID_RESULT_MESSAGES["en"]
    )


# 截斷提示（finish_reason='length' 時自動附加）。4 語齊全。
_TRUNCATION_NOTICES: dict[str, str] = {
    "zh-TW": "\n\n（⚠️ 回答因長度限制被截斷，如需完整內容請縮小範圍或追問特定細節。）",
    "zh-CN": "\n\n（⚠️ 回答因长度限制被截断，如需完整内容请缩小范围或追问特定细节。）",
    "en": "\n\n(⚠️ Response was truncated due to length limit. Narrow the scope or ask follow-up questions for full content.)",
    "ru": "\n\n(⚠️ Ответ был обрезан из-за ограничения длины. Сузьте область или задайте уточняющий вопрос для полного содержимого.)",
}


def _truncation_notice(language: str) -> str:
    """finish_reason='length' 截斷時的在地化提示。未支援 language 落回英文。"""
    if language and language.lower().startswith("zh"):
        # zh-CN / zh-HK 等變體用對應版，沒有就用 zh-TW
        return _TRUNCATION_NOTICES.get(language, _TRUNCATION_NOTICES["zh-TW"])
    return _TRUNCATION_NOTICES.get(language, _TRUNCATION_NOTICES["en"])


def _detect_and_annotate_truncation(
    response: str, result_data: dict, language: str
) -> str:
    """若 result.data.finish_reason == 'length'，在 response 末尾加截斷提示。

    多數 provider（OpenAI 相容、Anthropic）會在 AIMessage.response_metadata 設
    finish_reason；'length' 代表輸出被 max_tokens 截斷（Hermes #12770 / 諸多
    truncation bug 的根因）。claw_loop 抓到後自動告知使用者，避免「突然斷掉」
    的不良 UX。

    Args:
        response: 已清洗的 claw 回應。
        result_data: ``AgentResult.data`` dict。
        language: UI 語言 code。

    Returns:
        原始 response（無截斷）；或附加截斷提示後的 response。
    """
    if not isinstance(result_data, dict):
        return response
    finish_reason = result_data.get("finish_reason")
    if finish_reason != "length":
        return response
    if not response:
        return response  # 空回應交由既有 fallback 處理
    logger.warning(
        "[ClawLoop] response truncated (finish_reason=length), "
        f"response_len={len(response)}"
    )
    return response + _truncation_notice(language)


_LEDGER_AMOUNT_RE = None  # compiled lazily


def _ledger_hint_suffix(query: str, is_guest: bool = False) -> str:
    """金額訊息的確定性工具引導（2026-08-22）。

    為什麼必要：DeepSeek 對「花了 0.2 TON 買網域」這類小數+代幣句式
    的 tool 意圖辨識不穩（實測同 session 第二筆起尤其容易漏）——模型
    直接輸出「已送出記帳提案」的純文字幻覺（worker log used_tools=[]）。
    prompt 強化已做（shared.yaml 反模仿條款）但對隨機變異不夠；此處
    在 HumanMessage 尾部注入條件式系統提示，與時間錨點同機制（每輪可見）。

    只在偵測到「金額模式」時附加；條件句式（「若意圖是記錄」）避免
    誤傷純查價訊息（「比特幣多少錢」不含記錄意圖時模型自行判斷）。
    """
    global _LEDGER_AMOUNT_RE
    if _LEDGER_AMOUNT_RE is None:
        import re

        _LEDGER_AMOUNT_RE = re.compile(
            r"(\d+(?:\.\d+)?)\s*"
            r"(元|美元|台幣|美金|塊|TWD|USD|USDT|NT\$|US\$|\$|€|¥|TON|BTC|ETH|SOL|руб)"
            r"|記一筆|記帳|幫我記"
            # 中文口語常省單位：「午餐 250」「薪水 50000」——消費/收入詞＋裸數字
            r"|(午餐|晚餐|早餐|早點|咖啡|奶茶|計程車|車費|油錢|房租|水電|薪水|工資|薪資|獎金|紅包|支出|收入|消費|花了|付了|支付|花費)[^\d]{0,8}\d+",
            re.IGNORECASE,
        )
    if not _LEDGER_AMOUNT_RE.search(query or ""):
        return ""
    if is_guest:
        # 訪客：record_entry 需要 user_id（寫帳本）——工具不可用/回需登入。
        # 明確告訴模型不可幻覺「已記錄」，改引導登入（2026-08-23 盤點：
        # 訪客說「記一筆午餐100」得到「已記錄」的假成功回覆）。
        return (
            "\n\n[System] The user mentions an amount, but ledger recording "
            "requires login. Do NOT claim anything was recorded. Tell the "
            "user that bookkeeping needs an account and guide them to "
            "connect their wallet / log in."
        )
    return (
        "\n\n[System] This message contains an amount. If the user's intent "
        "is to RECORD this expense/income/trade, you MUST call the "
        "record_entry tool (a confirmation card will be shown; nothing is "
        "saved until approved). NEVER claim \"recorded/proposal sent\" in "
        "plain text without calling the tool. If the user is only asking "
        "about prices/market info, do not record."
    )


def _prepend_current_time_anchor(description: str) -> str:
    """在 task description 開頭強制錨定當前真實時間。

    為什麼必要：
    - LLM 訓練資料有 cutoff，會用舊資料填補
    - 純靠 system prompt 的「當前時間」會被長 ReAct loop 沖淡
    - 把時間直接放在 HumanMessage 最開頭，每輪都能被看到

    例：用戶問「PI 最新新聞」時，沒這個錨定，LLM 會編造 2024 年 KYC 截止；
    有錨定後，LLM 看到「今天是 2026/05/23」會自我修正，引用工具回的真實 published_at。
    """
    now_utc = datetime.now(timezone.utc)
    # Asia/Taipei = UTC+8
    now_tpe = now_utc + timedelta(hours=8)

    anchor = (
        f"[REF: 現在 {now_tpe.strftime('%Y-%m-%d %H:%M')} UTC+8 / "
        f"{now_utc.strftime('%Y-%m-%d %H:%M')} UTC]\n"
    )
    return anchor + description


def _clean_claw_response(text: str) -> str:
    """claw 直通模式的輕量清理。

    只清實際會出現的雜訊（幻覺網址、空連結、殘留 agent 標籤、**內部工具名稱洩漏**、
    **model 崩壞的 <unk> token 串**），**不做**舊合成層那套格式裁剪（如按關鍵詞
    刪「標的比較」段落）——輸出格式現在由 skill 驅動，不能被模板時代的 regex 反向破壞。
    """
    # Nemotron 等模型偶爾在長回應或 free tier 過載時，輸出整串 <unk>（tokenizer
    # 無法 decode 的垃圾 token）。這些內容對使用者毫無意義，直接清掉；若清洗後
    # 變空字串，claw_loop 會走既有 empty-response recovery / fallback 流程。
    text = _strip_unk_garbage(text)

    cleaned = re.sub(
        r"https?://(?:example\.(?:com|org|net)|fake-domain\.(?:com|org)|test\.(?:com|org))[/\w\-./?=&%#]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\[([^\]]*)\]\(\s*\)", r"\1", cleaned)
    cleaned = re.sub(
        r"^\[(?:chat|crypto|us_stock|tw_stock|commodity|forex|economic|tech|global_stock|cryptomind)\]\s*",
        "",
        cleaned,
        flags=re.MULTILINE,
    )
    # 移除內部工具名稱洩漏（【tool_name】、`tool_name`、(tool_name) 等）
    cleaned = _strip_tool_name_leaks(cleaned)
    # PII scrubbing — 遮罩助記詞/私鑰/信用卡/身分證/email/電話（防 echo 外洩）。
    # 單點 chokepoint：覆蓋 chat final response、DB 持久化、pulse 端點。
    # feature flag PII_SCRUB_ENABLED=false 可關閉。
    from core.validators.pii_scrubber import scrub_pii

    cleaned = scrub_pii(cleaned)
    return cleaned.strip()


# <unk> token 序列：model 偶發崩壞時產生。Nemotron free tier 在長回應或資源
# 壓力下特別容易出現。連續 5+ 個 <unk> 視為崩壞訊號，整段移除。
_UNK_PATTERN = re.compile(r"(?:<unk>){3,}")


def _strip_unk_garbage(text: str) -> str:
    """移除 model 崩壞的 <unk><unk>... 序列。

    Nemotron 等模型偶爾吐出數百個連續 <unk>（無法 decode 的 token）。判斷：
    - 若連續 <unk> 佔整個字串 50% 以上 → 視為完全崩壞，回空字串（走 recovery）
    - 否則只移除連續 <unk> 區塊，保留其餘文字

    本函式同時串接 E2/E3 崩壞偵測：
    - E2 _check_repetition_breakdown：phrase 重複 10+ 次（loop hallucination）
    - E3 _check_gibberish_breakdown：token salad（平均詞長 > 10 + 多 mixed-case）
    """
    # 先檢查重複 hallucination（E2）與亂碼（E3）—— 這些不需要 <unk> marker
    text = _check_repetition_breakdown(text)
    if not text:
        return ""  # E2 已判定崩壞
    text = _check_gibberish_breakdown(text)
    if not text:
        return ""  # E3 已判定崩壞

    if "<unk>" not in text:
        return text
    total_len = len(text)
    unk_count = text.count("<unk>")
    unk_total_len = unk_count * len("<unk>")
    if unk_total_len >= total_len * 0.5:
        # 崩壞嚴重 → 整段視為無效
        logger.warning(
            f"[ClawLoop] response dominated by <unk> tokens "
            f"({unk_count} occurrences, {unk_total_len}/{total_len} chars) — discarding"
        )
        return ""
    # 局部 <unk> → 只清掉連續區塊
    cleaned = _UNK_PATTERN.sub("", text)
    return cleaned


# 重複崩壞偵測：nemotron free tier 在資源壓力下會進入「loop hallucination」，
# 把同一個 phrase（通常是 skill/tool 名稱）重複數百次。S1 第二輪觀察到：
# 「Also there is 'us-stock-technical'. Also there is 'us-stock-technical'. ...」
# 重複數百次。判斷：若任一 8+ 字元的 phrase 出現 ≥10 次 → 崩壞。
_REPETITION_BREAKDOWN_THRESHOLD = 10
_REPETITION_PHRASE_MIN_LEN = 8


def _check_repetition_breakdown(text: str) -> str:
    """偵測 nemotron 的「loop hallucination」崩壞模式。

    觀察到的 case（S1 第二輪）：model 把 skill 名稱或短语重複數百次，
    例如「Also there is 'us-stock-technical'. Also there is 'us-stock-technical'. ...」

    判斷：用 sliding window 找任一 8+ 字元 phrase 出現 ≥10 次。
    若命中 → 整段視為崩壞（return ""，走 recovery）。

    一般正常金融分析不會把同 8 字元 phrase 重複 10+ 次（表格、條列都會有變化）。
    """
    if not text or len(text) < 200:
        return text  # 太短不可能是崩壞
    # 抓常見的重複單位：用 paragraph / sentence 切
    # 用 hash 計數每個 8-32 字元 substring
    from collections import Counter

    # 切成 phrases（用句號、換行、Also/There's 等分隔）
    # 簡化：直接 sliding window 看每 8-32 字元 substring 出現次數
    text_len = len(text)
    counter: Counter = Counter()
    # stride 4 避免暴力 O(n^2)；phrase 長度 8-32 字元
    for phrase_len in (16, 24, 32):
        for i in range(0, text_len - phrase_len, 4):
            chunk = text[i : i + phrase_len]
            # 只算含字母的（不算空白重複）
            if sum(1 for c in chunk if c.isalpha()) >= phrase_len // 2:
                counter[chunk] += 1
    if not counter:
        return text
    top_phrase, top_count = counter.most_common(1)[0]
    if top_count >= _REPETITION_BREAKDOWN_THRESHOLD:
        logger.warning(
            f"[ClawLoop] repetition breakdown detected: "
            f"phrase {top_phrase!r} repeated {top_count} times "
            f"({text_len} chars total) — discarding"
        )
        return ""
    return text


# ============================================================================
# E3: 亂碼崩壞偵測（gibberish detection）
#
# 觀察 S1 第 5 輪 smoke test：nemotron 偶爾輸出 35000+ 字元的「token salad」，
# 例如 "whetherurp/comp Wys pagomistenness[position Stock BXffeurpDowDowfwenness..."
# 特徵：
# - 平均 ASCII 詞長度 > 10（正常英文 4-6）
# - 大量 mixed-case words（如 "whetherurp", "Mistenness"）
# - 無中文/數字（純亂碼拼接）
# 正常金融分析不會有這些特徵（即使英文回應也是正常詞彙）。
# ============================================================================

# 亂碼偵測門檻
_GIBBERISH_MIN_TEXT_LEN = 500  # 太短不檢測
_GIBBERISH_AVG_ASCII_WORD_LEN = 10.0  # 平均 ASCII 詞長 > 10 視為亂碼
_GIBBERISH_MIXED_CASE_RATIO = 0.5  # > 50% ASCII 詞是 mixed-case 視為亂碼


def _check_gibberish_breakdown(text: str) -> str:
    """偵測 nemotron 的「token salad」亂碼模式。

    觀察到的 case：model 輸出數萬字元的亂碼拼接，例如
    "whetherurp Wys pagomistenness BXffeurpDowDowfwenness..."

    判斷（必須三條件 AND）：
    1. 文字夠長（>= 500 字元）
    2. 平均 ASCII 詞長度 > 10（正常英文 4-6）
    3. > 50% ASCII 詞是 mixed-case（大小寫混合）

    正常金融分析不會命中（即使是表格 + 條列，詞都是 dictionary words）。
    若命中 → 整段視為崩壞（return ""，走 recovery）。
    """
    if not text or len(text) < _GIBBERISH_MIN_TEXT_LEN:
        return text

    # 切詞：用 whitespace
    words = text.split()
    if not words:
        return text

    # 只看 ASCII 詞（排除中文/emoji）
    ascii_words = [w for w in words if w and all(c.isascii() for c in w if c.isalpha())]
    if not ascii_words:
        return text  # 全中文之類，不檢測

    # 條件 1：平均 ASCII 詞長度
    avg_len = sum(len(w) for w in ascii_words) / len(ascii_words)
    if avg_len <= _GIBBERISH_AVG_ASCII_WORD_LEN:
        return text

    # 條件 2：mixed-case 比例
    mixed_case_count = sum(
        1
        for w in ascii_words
        if any(c.isupper() for c in w) and any(c.islower() for c in w)
    )
    mixed_case_ratio = mixed_case_count / len(ascii_words)
    if mixed_case_ratio < _GIBBERISH_MIXED_CASE_RATIO:
        return text

    logger.warning(
        f"[ClawLoop] gibberish breakdown detected: "
        f"avg_ascii_word_len={avg_len:.1f}, mixed_case_ratio={mixed_case_ratio:.2f}, "
        f"text_len={len(text)} — discarding"
    )
    return ""


# ============================================================================
# Chat-template special token / scaffolding 清洗
#
# 用 OpenRouter 接多個 model（含 self-host），偶爾會把 chat-template 的
# special token 或 internal scaffolding 標記直接 decode 進可見回應裡，例如：
#   <|im_start|>system 你是助理 <|im_end|>        (Qwen / ChatML)
#   <start_of_turn>model ... <end_of_turn>         (Gemma)
#   <|begin_of_text|> ... <|endoftext|>             (Llama)
#   <system-reminder>...</system-reminder>          (OpenAI 內部)
#   <tool_call>...</tool_call> / <function_calls>   (function-calling scaffolding)
#   <system>...</system>                            (通用 role tag)
# 這些對使用者毫無意義，且 <system-reminder> / <tool_call> 還可能被前端誤判
# 為結構化指令。直接 strip 掉。
#
# 放在 _strip_tool_name_leaks 而非 _clean_claw_response：因為 _StreamSanitizer
# 預設 sanitizer 就是 _strip_tool_name_leaks（claw_loop.py:413），改這一支可讓
# 「串流即時 emit」與「最終回應」兩條 path 同時覆蓋；_clean_claw_response 會
# 透過 line 153 呼叫 _strip_tool_name_leaks 自動繼承。
#
# 所有 token 長度 < _STREAM_SANITIZER_TAIL(=40)，最長的 <system-reminder>(17)，
# 跨 chunk 邊界都能被 buffer 重組後清掉。
# ============================================================================
_SPECIAL_TOKEN_PATTERN = re.compile(
    r"<\|im_start\|>"
    r"|<\|im_end\|>"
    r"|<\|system\|>"
    r"|<\|user\|>"
    r"|<\|assistant\|>"
    r"|<\|begin_of_text\|>"
    r"|<\|endoftext\|>"
    r"|<system-reminder>"
    r"|</system-reminder>"
    r"|<system>"
    r"|</system>"
    r"|<tool_call>"
    r"|</tool_call>"
    r"|<function_call>"
    r"|</function_call>"
    r"|<function_calls>"
    r"|</function_calls>"
    r"|<start_of_turn>"
    r"|<end_of_turn>"
)


def _strip_tool_name_leaks(text: str) -> str:
    """移除 LLM 在回應中殘留的內部工具名稱。

    LLM 常把工具引用寫進回應給使用者看（例如「資料來源：【get_crypto_price】」、
    「來源：us_stock_price」），這會暴露內部架構 + 不專業。本函式移除常見模式：

    - ``【tool_name】`` / ``[tool_name]`` / ``(tool_name)`` / `` `tool_name` ``
    - 行末或括號內的裸 tool_name（如「來源：us_stock_price」）
    - **裸 tool name**（如「我用了 get_crypto_price 查到」）— 2026-07-20 新增
    - **chat-template special token**（如 ``<|im_start|>``、``<system-reminder>``、
      ``<tool_call>``）— 2026-07-23 新增（對齊 OpenClaw strip scaffolding 做法）

    **強化歷程**：
    - A1（D3）：改用 ``tool_name_registry`` 動態讀，取代硬編碼清單。
    - D3 補強：自動產生 ``<name>_tool`` 變體（LangChain @tool handler 慣例）。
    - **G6 效能修復**：原版每次 call 重建 ~240 個 regex + 跑 ~1200 次 re.sub，
      對長回應是顯著 CPU。改用 ``_get_compiled_sanitizer_patterns()`` 預編譯
      alternation regex（5 個），module-level cache，bootstrap 時 invalidate。
    - **2026-07-20**：新增 ``_get_compiled_bare_name_pattern()`` 處理無包圍符號
      的裸 name 殘留（pattern [5]）。只對 len >= 8 的 long name 套用 + 邊界
      lookbehind/lookahead，避免誤殺正常英文。
    """
    from core.agents.tool_name_registry import (
        _get_compiled_bare_name_pattern,
        _get_compiled_sanitizer_patterns,
    )

    patterns = _get_compiled_sanitizer_patterns()
    # 4 個 pure-removal pattern（pattern[0..3]）：抓到就刪
    for p in patterns[:4]:
        text = p.sub("", text)
    # 第 5 個 pattern：來源：<tool_name> → 來源：即時工具查詢
    text = patterns[4].sub(r"\1：即時工具查詢", text)
    # 第 6 個 pattern：裸 tool name（無包圍符號）
    text = _get_compiled_bare_name_pattern().sub("", text)

    # 清理可能殘留的空括號（半形 + 全形）
    text = re.sub(r"【\s*】", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"（\s*）", "", text)
    # 清理 chat-template special token / scaffolding（<|im_start|> 等）
    text = _SPECIAL_TOKEN_PATTERN.sub("", text)
    # 清理多餘空格
    text = re.sub(r"  +", " ", text)
    return text


# ============================================================================
# _StreamSanitizer — 串流 token 的即時 sanitizer
#
# 問題：_strip_tool_name_leaks 對完整字串做 regex，但 SSE token 是片段
# （可能切在 `【get_` / `crypto_price】` 中間）。直接對單一 chunk 做 regex
# 會漏判跨 chunk 的 tool name。
#
# 解法：「全 buffer sanitize + 增量 emit」。
#   - dirty_buffer：累積所有原始 LLM token
#   - emitted_offset：已 emit 給 SSE 的 cleaned 字元數（避免重複 emit）
#   - 每次收到 chunk：
#       1. dirty_buffer += chunk
#       2. cleaned = sanitize(dirty_buffer)  # 全 buffer 重做
#       3. safe_end = len(cleaned) - SAFETY_TAIL
#          （保留末段 SAFETY_TAIL 字元，因為這段可能還接續新 chunk 形成跨邊界 tool name）
#       4. if safe_end > emitted_offset:
#            emit cleaned[emitted_offset : safe_end]
#            emitted_offset = safe_end
#   - flush：emit cleaned[emitted_offset:]（剩餘全 emit）
#
# 為什麼 cleaned[:emitted_offset] 在多次 feed 間穩定？
#   - sanitize 是 deterministic：同樣輸入永遠同樣輸出
#   - 跨邊界的 tool name 只影響 buffer 末段（長度 < 最長 tool name + 包圍 = ~40）
#   - 因此每次重做 sanitize 後，cleaned 的前綴（扣除末 40 字元）與上次相同
#   - emitted_offset 永遠 <= len(cleaned) - SAFETY_TAIL，所以已 emit 的部分
#     不會被未來的跨邊界 tool name 影響 → 不會重複 emit、不會漏 emit
#
# SAFETY_TAIL 選 40：
#   - 最長 tool name: `get_crypto_categories_and_gainers`（30）+ `_tool` = 35
#   - 包圍符號: 最多 4 字元（【】、（））
#   - 餘裕：1 字元
#   - 合計 ~40
# ============================================================================

_STREAM_SANITIZER_TAIL = 40


class _StreamSanitizer:
    """串流 token 的 buffer-based sanitizer。

    用法：
        sanitizer = _StreamSanitizer()
        for chunk in stream:
            safe_chunk = sanitizer.feed(chunk)
            if safe_chunk:
                emit_to_sse(safe_chunk)
        tail = sanitizer.flush()
        if tail:
            emit_to_sse(tail)

    設計取捨：buffer 末段（SAFETY_TAIL 字元）會延遲 emit，確保跨 chunk 邊界
    的 tool name 都能被完整清洗。代價是打字機效果比 raw 串流延遲 ~SAFETY_TAIL
    字元，但 final event 會用完整 sanitize 的內容覆蓋，使用者最終看到的是正確的。
    """

    def __init__(self, sanitizer_fn=_strip_tool_name_leaks) -> None:
        self._buffer = ""
        self._emitted_offset = 0  # 已 emit 的 cleaned 字元數
        self._sanitize = sanitizer_fn

    def feed(self, chunk: str) -> str:
        """喂入一個 chunk，回傳「本次新增、確認安全可立即送出」的內容。

        保留末段（_STREAM_SANITIZER_TAIL 字元）在下次處理。回傳值已 sanitize。
        """
        if not chunk:
            return ""
        self._buffer += chunk
        cleaned = self._sanitize(self._buffer)
        # 安全 emit 範圍：保留末段 SAFETY_TAIL 字元
        safe_end = max(0, len(cleaned) - _STREAM_SANITIZER_TAIL)
        if safe_end <= self._emitted_offset:
            return ""  # 沒有新的安全內容可 emit
        emit_text = cleaned[self._emitted_offset : safe_end]
        self._emitted_offset = safe_end
        return emit_text

    def flush(self) -> str:
        """stream 結束時呼叫，回傳剩餘 buffer 經 sanitize 的內容（最後一段）。"""
        if not self._buffer:
            return ""
        cleaned = self._sanitize(self._buffer)
        remaining = cleaned[self._emitted_offset :]
        self._buffer = ""
        self._emitted_offset = 0
        return remaining


class _ToolStepTracker:
    """agent_start / agent_finish 的步驟記帳（依工具名）。

    並行 tool_calls（同一輪 AIMessage 帶多個呼叫）會連續觸發多個 on_tool_start，
    ToolMessage 再依各自完成順序回流。若 finish 用「當前計數」當 step，所有
    finish 都會打到最後一列，前面列的 spinner 永遠不會變 ✓（2026-08-25
    線上回報：六個工具列全部持續轉圈）。用具名記帳讓每個 finish 指向自己
    start 時拿到的步驟號。
    """

    def __init__(self) -> None:
        self._count = 0
        self._by_name: dict = {}

    def start(self, name: str) -> int:
        self._count += 1
        self._by_name[name] = self._count
        return self._count

    def end(self, name: str) -> int:
        return self._by_name.get(name, self._count)


class ClawLoopMixin(ManagerAgentMixin):
    """CLAW 直通模式的單節點實作。"""

    def _resolve_memory_context(self) -> Optional[str]:
        """載入長期記憶 context，失敗時靜默回 None（不阻塞主流程）。"""
        try:
            return self.get_long_term_memory_context() or None
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return None

    async def _resolve_experience_hint(self, query: str) -> Optional[str]:
        """載入相關過去經驗(方向①:讓 agent 記得類似問題怎麼解過)。

        從 task_experiences 表用 FTS 檢索與當前 query 相關的過去軌跡,
        格式化成 prompt 區塊注入。失敗時靜默回 None(不阻塞主流程)。

        設計決策:
        - llm=None 跳過 layer-3 LLM rerank(省一次 LLM 呼叫,串流路徑上要快)
        - 只在 user_id 存在時查(訪客/匿名無經驗可查)
        - task_family=None 跨 family 檢索(P0-1:寫入端 family 是 crypto/tw_stock/…，精確比對 chat 永遠漏掉)
        """
        user_id = getattr(self, "user_id", None)
        if not user_id:
            return None
        try:
            from core.database.experiences import ExperienceStore

            rows = await run_sync(
                ExperienceStore().retrieve_relevant,
                user_id,
                None,  # task_family=None:跨 family（P0-1——精確比對 'chat' 會漏掉 crypto/tw_stock 等）
                query,
                None,  # llm=None:跳過 rerank
            )
            if not rows:
                return None
            return ExperienceStore().format_for_prompt(rows)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return None

    def _friendly_fallback(self, error: BaseException, state: Dict) -> str:
        """把底層 LLM 例外轉成使用者可理解的訊息，並 fire response hooks。

        無法辨識的錯誤才退回通用 fallback——避免把「Error code: 429 - {...」
        這類原文噴進聊天泡泡。對齊 base_react_agent._error_result 的策略。
        """
        from core.agents.base_react_agent import _friendly_llm_error
        from core.i18n import t

        language = getattr(self, "language", "zh-TW")
        fallback = (
            _friendly_llm_error(str(error), language)
            or t("errors.analysis.cannot_process", language)
        )
        self._invoke_response_hooks(state, fallback)
        return fallback

    def _extract_clarify_target(self, raw_query: str) -> str:
        """從 user query 抽出要查詢的 ticker / 名稱（給 multi-market lookup 用）。

        優先用 clarification._detect_query_ticker（抓大寫英文 ticker）。
        抓不到就用整個 query（中文公司名場景，multi_market_resolver 也能處理）。
        """
        try:
            from core.agents.clarification import _detect_query_ticker

            ticker = _detect_query_ticker(raw_query)
            return ticker or raw_query.strip()
        except Exception:
            return raw_query.strip()

    def _build_multi_market_question(
        self, ticker_or_query: str, language: str
    ) -> str:
        """跑 resolve_symbol_all_markets 並組最終 clarification 訊息。

        失敗時 fallback 到基本 4 選項 clarification（不阻塞流程）。
        """
        try:
            from core.agents.clarification import (
                _build_basic_clarification as _fallback_msg,
            )
            from core.agents.clarification import (
                build_multi_market_clarification,
            )
            from core.tools.multi_market_resolver import (
                resolve_symbol_all_markets_sync,
            )

            candidates_json = resolve_symbol_all_markets_sync(ticker_or_query)
            final = build_multi_market_clarification(
                ticker_or_query, candidates_json, language=language
            )
            return final
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.warning(
                "[ClawLoop] multi-market lookup failed for %r: %s — fallback to basic",
                ticker_or_query,
                e,
            )
            try:
                from core.agents.clarification import (
                    _build_basic_clarification as _fallback_msg,
                )

                return _fallback_msg(ticker_or_query)
            except Exception:
                return (
                    f"您查詢的「{ticker_or_query}」可能是多種資產。"
                    "請問您指的是加密貨幣、美股、台股，還是其他市場？"
                )

    async def _claw_loop_node(self, state: Dict) -> Dict:
        """單迴圈節點：直接把用戶問題交給 cryptomind ReAct loop。"""
        from ._main import (
            AGENT_EXECUTION_TIMEOUT,
            _get_history_for_prompt,
            _run_background,
        )

        raw_query = state["query"]
        query = sanitize_user_input(raw_query)
        language = getattr(self, "language", "zh-TW")

        # （M2 曾把查詢也攔去 pipeline，但那會讓 LLM 無法解析自然語言、反而變笨，
        #  已改回 ReAct。pipeline 保留給 M3 執行用。）

        # bootstrap 複用 Manager 時 session_id 可能是上一個請求的
        state_session_id = state.get("session_id")
        if state_session_id and state_session_id != self.session_id:
            self.session_id = state_session_id
            self._memory_store = None
            logger.debug(f"[ClawLoop] session_id synced to: {state_session_id}")

        # 重設 per-request flag（G2 修復）：
        # _numeric_verified / _clarified 此前挂在 self 上，但 bootstrap LRU cache
        # 會在同一個 (user, session_id) tuple 內重用 ManagerAgent，導致這些 flag
        # 跨請求殘留——第一個請求觸發後，後續請求的 Phase B verification 與 Phase C
        # clarification 都會被永久 skip。改為每個請求開始時重設。
        self._numeric_verified = False
        self._clarified = False
        # G3 修復：fallback_used 必須在函式最外層初始化，否則當 response 非空時
        # 不會進 `if not response:` block，fallback_used 從未賦值 → NameError。
        fallback_used = False
        # Fallback guard：每個 turn 重設（學 Hermes「每輪最多一次」）。
        try:
            from core.agents.fallback import reset_turn_fallback_guard

            reset_turn_fallback_guard()
        except Exception:
            pass  # fallback 模組故障不阻塞主流程

        # 工具呼叫防護：每個 turn 重設計數器與去重視窗。
        # 防 reasoning 模型反覆搜尋/抓網頁同一主題跑滿 timeout（線上 #特斯拉案例）。
        try:
            from core.agents.tool_guard import reset_turn_tool_guard

            reset_turn_tool_guard()
        except Exception:
            pass  # tool_guard 模組故障不阻塞主流程

        # check_idle_consolidation() 內部讀 DB（get_last_consolidated_index），
        # 是同步 I/O——在 async node 內直接呼叫會阻塞 event loop。走 run_sync。
        # 記憶整合是背景輔助功能，DB 失敗時絕不可讓主對話崩潰。
        try:
            need_consolidation = await run_sync(self.check_idle_consolidation)
        except Exception as exc:
            logger.warning(
                "[ClawLoop] check_idle_consolidation failed (DB?)—跳過整合不阻塞對話: %s",
                exc,
            )
            need_consolidation = False
        if need_consolidation:
            logger.info("[ClawLoop] Auto-triggering idle consolidation")
            _run_background(self._background_memory_consolidation())

        from core.i18n import t

        self._emit_progress(
            "understand_intent", t("ui_messages.progress.analyzing_request", language)
        )

        agent = self.agent_registry.get("cryptomind")
        if not agent or not hasattr(agent, "execute_streaming"):
            logger.error("[ClawLoop] cryptomind agent unavailable")
            fallback = t("errors.analysis.system_init_error", language)
            self._invoke_response_hooks(state, fallback)
            return {"final_response": fallback, "_processed_query": raw_query}

        # M6 修復（2026-07-20）：_get_history_for_prompt 內部呼叫 _read_compact_for_manager
        # → core.database.memory.read_compact_state（sync DB SELECT）。history 過長時才
        # 觸發，但仍會凍結 event loop。包進 run_sync。
        history = await run_sync(
            lambda: _get_history_for_prompt(
                state.get("history", ""),
                user_id=self.user_id or "anonymous",
                session_id=self.session_id,
            )
        )

        # 方向①:載入相關過去經驗(讓 agent 記得類似問題怎麼解過)。
        # 與 memory_context 並列注入,失敗時為 None(靜默,不阻塞)。
        experience_hint = await self._resolve_experience_hint(raw_query)

        task = SubTask(
            step=0,
            description=_prepend_current_time_anchor(query)
            + _ledger_hint_suffix(raw_query, is_guest=not getattr(self, "user_id", None)),
            agent="cryptomind",
            context={
                "original_query": raw_query,
                "history": history,
                "language": getattr(self, "language", "zh-TW"),
                "memory_context": self._resolve_memory_context(),
                "experience_hint": experience_hint,
                # Premium 使用者自訂（analysis.py:871-872 從 DB 讀入 state）：
                # system_prompt 已過 sanitize_system_prompt；enabled_tools 走交集
                # 限縮（_filter_tool_metas 只能再縮窄、不能解鎖被關掉的工具）。
                "system_prompt": state.get("system_prompt"),
                "enabled_tools": state.get("enabled_tools") or [],
                # Agent preset（Phase 2）：server-side capability resolver 結果。
                # API 層已把 enabled_tools 交集進 tool_names；此處只是傳遞。
                "preset_config": state.get("preset_config"),
            },
        )

        # 串流 sanitizer：token chunk 可能切在 tool name 中間（如「【get_」+
        # 「crypto_price】」），必須用 buffer 重組後再 sanitize，否則跨 chunk
        # 的 tool name 會漏判、被直接 emit 給前端使用者。
        # 詳見 _StreamSanitizer docstring。
        stream_sanitizer = _StreamSanitizer()

        def _emit_safe_token(safe_text: str) -> None:
            if not safe_text:
                return
            try:
                self._emit_progress(
                    "synthesize_response",
                    t("ui_messages.progress.synthesizing", language),
                    type="token",
                    data={"chunk": safe_text},
                )
            except Exception:
                pass

        def _on_token(token: str) -> None:
            # 先經 sanitizer buffer 重組 + 清洗，再 emit 給 SSE
            _emit_safe_token(stream_sanitizer.feed(token))

        def _flush_stream_sanitizer() -> None:
            """每次 execute_streaming 結束時呼叫，emit buffer 剩餘安全內容。"""
            _emit_safe_token(stream_sanitizer.flush())

        def _on_tool_start(name: str) -> None:
            try:
                # 把內部 tool_id 對應到 display_name，避免 SSE progress 事件
                # 洩漏內部架構（如「正在查詢：get_crypto_price」→「正在查詢：即時加密貨幣價格」）。
                # task_id / task_name 也用 display_name，確保整個 SSE payload 不含原始 ID。
                # i18n（Bug#1）：傳入 language，讓 display_name 跟 UI 語言一致。
                from core.agents.tool_name_registry import get_tool_display_name

                display = get_tool_display_name(name, language)
                step = _tool_steps.start(name)
                self._emit_progress(
                    "execute_task",
                    t("ui_messages.progress.querying_tool", language, name=display),
                    type="agent_start",
                    task_id=display,
                    task_name=display,
                    step=step,
                    agent="cryptomind",
                    parallel=False,
                )
            except Exception:
                pass

        def _on_tool_end(name: str) -> None:
            try:
                from core.agents.tool_name_registry import get_tool_display_name

                display = get_tool_display_name(name, language)
                self._emit_progress(
                    "execute_task",
                    t("ui_messages.progress.tool_done", language, name=display),
                    type="agent_finish",
                    task_id=display,
                    task_name=display,
                    step=_tool_steps.end(name),
                    agent="cryptomind",
                    success=True,
                    parallel=False,
                )
            except Exception:
                pass

        # ── idle-aware agent runner（雙時鐘 timeout）──────────────────────────
        # ── agent runner（移除時間 timeout，只靠 recursion_limit）─────────────
        # 2026-08-02 改：移除 idle watchdog + wall-clock 600s（會誤殺 reasoning
        # model 思考、free tier 排隊、開放式問題規劃）。對齊 ChatGPT/Claude/
        # LangGraph 官方做法——用步數限制（recursion_limit=25）而非秒數。
        # 保留極寬鬆 wall-clock safety net（AGENT_EXECUTION_TIMEOUT=1800s）
        # 只防「每步正常但永遠跑不完」的理論異常。
        _tool_steps = _ToolStepTracker()

        async def _run_agent(agent_task) -> Any:
            """跑 execute_streaming，帶極寬鬆 wall-clock safety net。

            主要保護是 LangGraph 的 recursion_limit=25（擋無限迴圈）。
            AGENT_EXECUTION_TIMEOUT（預設 30 分鐘）只在理論異常時觸發。
            """
            try:
                result = await asyncio.wait_for(
                    agent.execute_streaming(
                        agent_task,
                        on_token=_on_token,
                        on_tool_start=_on_tool_start,
                        on_tool_end=_on_tool_end,
                    ),
                    timeout=AGENT_EXECUTION_TIMEOUT,
                )
                return result
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise

        # ============================================================
        # Consent Gate（Trustworthy AI — Policy Gate 支柱）
        # ------------------------------------------------------------
        # 在 agent 真正執行前，掃描可用工具池（零 LLM、純同步）。若含 high-risk
        # tool 且使用者身分信任度不足 → 透過既有 HITL interrupt 彈出 consent。
        # 同意/拒絕都記 audit log（事後追溯）。
        #
        # 意圖過濾（避免過度觸發）：原本掃整池，導致「問比特幣價格」也彈 KYC consent。
        # 現在依 query 意圖過濾——純查詢不彈；query 涉及錢包/KYC/交易才彈。
        # 已 granted 的 session 保留全部（不重彈）。
        # ============================================================
        consent_granted = bool(state.get("consent_granted", False))
        consent_assessment = None
        high_risk_tools = []
        try:
            from core.agents.manager.consent_gate import (
                append_guard_audit_receipt,
                assess_user_trust,
                build_consent_payload,
                log_consent_decision,
                parse_consent_answer,
                scan_high_risk_tools,
                should_require_consent,
            )

            tool_metas = agent._filter_tool_metas(task)
            all_high_risk = scan_high_risk_tools(tool_metas)
            # 意圖過濾：只在本 session 尚未同意過時，依 query 過濾 high-risk tool。
            # 已 granted → 保留全部（不重彈，consent_granted 短路 should_require_consent）。
            # 未 granted → 只保留 query 真的可能用到的（純查詢不彈 consent）。
            if consent_granted:
                high_risk_tools = all_high_risk
            else:
                high_risk_tools = _filter_high_risk_by_intent(all_high_risk, raw_query)
            # 評估身分信任度（Identity Trust Layer）。wallet_verified = 有 session user。
            wallet_addr = getattr(self, "wallet_address", None)
            consent_assessment = assess_user_trust(
                wallet_verified=bool(wallet_addr or self.user_id),
            )
            if should_require_consent(
                high_risk_tools, consent_assessment, already_granted=consent_granted
            ):
                # 接活既有 HITL：interrupt 後 analysis.py 的 __interrupt__ 接收端
                # 會 emit hitl_question 給前端；使用者回應後 resume 回此處。
                from langgraph.types import interrupt

                payload = build_consent_payload(
                    high_risk_tools, consent_assessment,
                    language=getattr(self, "language", "zh-TW"),
                )
                answer = interrupt(payload)
                parsed = parse_consent_answer(answer)
                approved = parsed["approved"]
                log_consent_decision(
                    user_id=self.user_id,
                    username=getattr(self, "display_name", None),
                    high_risk_tools=high_risk_tools,
                    assessment=consent_assessment,
                    approved=approved,
                )
                await append_guard_audit_receipt(
                    user_id=self.user_id,
                    event_type="agent.consent",
                    payload={
                        "approved": approved,
                        "tools": [item.name for item in high_risk_tools],
                        "trust": consent_assessment.to_audit_metadata(),
                    },
                )
                if not approved:
                    declined_msg = t(
                        "consent.high_risk_declined", language,
                    ) if False else "使用者拒絕了高風險操作的同意請求，已取消執行。"
                    self._invoke_response_hooks(state, declined_msg)
                    return {
                        "final_response": declined_msg,
                        "_processed_query": raw_query,
                        "consent_granted": False,
                    }
                # 同意 → 標記本次 session 已 granted，resume 後續執行不重彈
                consent_granted = True
            elif high_risk_tools and consent_assessment:
                # 信任度足夠（如已過 personhood）→ 不彈 consent 但仍記 audit
                log_consent_decision(
                    user_id=self.user_id,
                    username=getattr(self, "display_name", None),
                    high_risk_tools=high_risk_tools,
                    assessment=consent_assessment,
                    approved=True,
                )
                await append_guard_audit_receipt(
                    user_id=self.user_id,
                    event_type="agent.consent_reused",
                    payload={
                        "approved": True,
                        "tools": [item.name for item in high_risk_tools],
                        "trust": consent_assessment.to_audit_metadata(),
                    },
                )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except GraphInterrupt:
            # interrupt() 內部 raise GraphInterrupt（Exception 子類）來暫停 graph，
            # 這是 Consent Gate 正常觸發的 control-flow，不是故障——必須原樣上拋
            # 給 LangGraph 執行器，否則會被下方 except Exception 誤捕並記成「故障」。
            raise
        except Exception as e:
            logger.error("[ClawLoop] Consent Gate failure: %s", e)
            if high_risk_tools:
                blocked_msg = "高風險操作的授權檢查未完成，這次操作已停止。"
                self._invoke_response_hooks(state, blocked_msg)
                return {
                    "final_response": blocked_msg,
                    "_processed_query": raw_query,
                    "consent_granted": False,
                }

        # 把 consent 結果存進 agent，供 wrap_tool 稽核層讀取（事後追溯防線）
        try:
            setattr(agent, "_consent_granted", consent_granted)
            setattr(agent, "_consent_assessment", consent_assessment)
        except Exception:
            pass

        try:
            result = await _run_agent(task)
        except asyncio.TimeoutError:
            logger.error(f"[ClawLoop] timed out (wall>{AGENT_EXECUTION_TIMEOUT}s safety net)")
            fallback = t(
                "errors.analysis.timeout", language, seconds=AGENT_EXECUTION_TIMEOUT
            )
            self._invoke_response_hooks(state, fallback)
            return {"final_response": fallback, "_processed_query": raw_query}
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            # Hermes-style:暫時性錯誤（rate limit 429 / 供應商 5xx InternalServerError）
            # 值得重試一次——等 slot 釋放或過載緩解就能成功。其他錄誤（401/403/402）
            # fail-fast 走友善訊息——重試必然失敗，只會浪費免費方案的寶貴額度。
            if _is_transient(e):
                # Worker 並發過載（NIM "Worker local total request limit"）的 slot
                # 釋放時間遠長於一般 429——大模型推論常 5-30 秒。短 backoff（2s）
                # 幾乎必然落在同一擁擠 window，retry 必然再 exhausted。對齊友善訊息
                # 承諾的 ~30 秒；一般 429/5xx 維持短 backoff（2s）即可。
                backoff = 30 if _is_worker_overload(e) else 2
                logger.warning(
                    f"[ClawLoop] transient error, retrying once (backoff={backoff}s): {e}"
                )
                await asyncio.sleep(backoff)
                try:
                    result = await _run_agent(task)
                except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                    raise
                except Exception as e2:
                    logger.error(f"[ClawLoop] retry exhausted: {e2}")
                    fallback = self._friendly_fallback(e2, state)
                    return {
                        "final_response": fallback,
                        "_processed_query": raw_query,
                    }
            else:
                logger.error(f"[ClawLoop] execution failed: {e}")
                fallback = self._friendly_fallback(e, state)
                return {"final_response": fallback, "_processed_query": raw_query}

        used_tools = []
        if isinstance(result.data, dict):
            used_tools = result.data.get("used_tools", []) or []

        # Flush 串流 sanitizer 的剩餘 buffer（這一輪 LLM 串完，剩餘內容安全）
        _flush_stream_sanitizer()
        response = _clean_claw_response(result.message)

        # ============================================================
        # Recovery：claw_loop 層的二次嘗試
        #
        # base_react_agent.execute_streaming 內部已經有 4 層 recovery，
        # 但若 LLM 仍回空 / 模糊訊息，這裡再多一次機會：
        # 當「沒用任何工具 + response 空」時，push 一個更強的 nudge 重跑。
        #
        # 這層專解「LLM 看到查詢直接放棄、連工具都沒試」的 case
        # （例如 SNXX / 不存在的幣），讓 LLM 至少嘗試 resolve_symbol /
        # web_search，或明確告知「查無此標的」而非 fallback message。
        # ============================================================
        from core.i18n import t

        _claw_retried = False
        # 觸發強 nudge retry 的條件：
        # 1. 沒用任何工具（used_tools 空）
        # 2. response 空 OR agent 明確回報失敗（result.success=False）
        #
        # 修復（2026-07-30，log 鐵證）：原本只看 `not response`，但
        # base_react_agent 回空時會把 empty_response_message（26字錯誤訊息）
        # 塞進 result.message → response 非空 → 強 nudge retry 被跳過。
        # 中等模型（DeepSeek 等）面對綜合判斷問題（如「美股適合買嗎」）
        # 兩次都回空，base_react_agent 的 4 層 recovery 都沒救回來，
        # result.success=False，但 claw_loop 因為 response 非空而放過了
        # 第二層補救機會。加上 success 判斷，讓 agent 自承失敗時也觸發。
        if (
            not used_tools
            and not _claw_retried
            and (not response or not getattr(result, "success", True))
        ):
            _claw_retried = True  # local flag，避免同一請求內無限迴圈
            try:
                logger.info(
                    "[ClawLoop] empty response without tools, retrying with strong nudge"
                )
                # F2: 0.5s backoff（學 Hermes #35230）避免同一 rate-limit window 連續重試
                await asyncio.sleep(0.5)
                nudge_task = SubTask(
                    step=task.step + 1,
                    description=(
                        f"{query}\n\n"
                        + t("llm_sections.nudge.empty_reply_no_tools", language)
                    ),
                    agent=task.agent,
                    context=task.context,
                )
                result = await _run_agent(nudge_task)
                if isinstance(result.data, dict):
                    used_tools = result.data.get("used_tools", []) or []
                _flush_stream_sanitizer()
                response = _clean_claw_response(result.message)
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.warning(f"[ClawLoop] strong nudge retry failed: {e}")

        # ============================================================
        # Phase B：Numeric Verification（防幻覺）
        #
        # 學 outcome grading + post-hoc verification（arXiv hallucination survey）。
        # 當 response 非空時，檢查金融關鍵數字是否都能在 tool 輸出中找到來源。
        # 若有可疑幻覺（如「660 點」不在 tool 輸出）→ nudge LLM 重跑一次。
        # 最多 1 次（避免 token 浪費）。
        # ============================================================
        if response and used_tools and not getattr(self, "_numeric_verified", False):
            self._numeric_verified = True
            try:
                from core.agents.verification import verify_numeric_consistency

                tool_outputs = []
                if isinstance(result.data, dict):
                    tool_outputs = result.data.get("tool_outputs", []) or []
                if tool_outputs:
                    verification = verify_numeric_consistency(response, tool_outputs)
                    if verification.has_hallucination_risk:
                        suspicious_vals = [
                            n.value for n in verification.suspicious_numbers
                        ]
                        logger.warning(
                            f"[ClawLoop] numeric hallucination detected: "
                            f"{suspicious_vals} — nudging for correction"
                        )
                        nudge_task = SubTask(
                            step=task.step + 1,
                            description=(
                                f"{query}\n\n"
                                "⚠️ 你的上一個回應中包含無法從工具結果驗證的數字"
                                f"（{suspicious_vals}）。請重新基於工具實際返回的數字"
                                "回答，不要推論或幻覺任何工具未提供的數字。"
                            ),
                            agent=task.agent,
                            context=task.context,
                        )
                        result = await _run_agent(nudge_task)
                        _flush_stream_sanitizer()
                        response = _clean_claw_response(result.message)
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.warning(f"[ClawLoop] numeric verification failed: {e}")

        # ============================================================
        # Phase C：Progressive Clarification（學 LangGraph HITL）
        #
        # 當 LLM 說「查無 / 不確定」且沒用任何工具時，不直接放棄，
        # 而是主動問使用者「您指的 SNXX 是加密貨幣還是美股？」
        # 走既有 HITL 機制（analysis.py Command(resume=...)）。
        # 每 session 最多觸發 1 次（避免無限追問）。
        #
        # 2026-07-20 強化（AKE 案例）：
        # 當 LLM **沒用工具卻編造**「正在獲取即時價格...」「RSI 分析...」時，
        # should_clarify 回傳 ``_MULTI_MARKET_TRIGGER_SENTINEL``，指示這裡要：
        #   1. 跑 ``resolve_symbol_all_markets`` 並行查所有市場
        #   2. 把真實候選嵌進 clarification 訊息（不再用空泛的「請問是哪類」）
        # 商業誠實原則：候選含「本平台不支援」的市場也要誠實列出。
        # ============================================================
        if response and not used_tools:
            try:
                from core.agents.clarification import (
                    is_multi_market_trigger,
                    should_clarify,
                )

                already_clarified = getattr(self, "_clarified", False)
                question = should_clarify(
                    response=response,
                    used_tools=used_tools,
                    query=raw_query,
                    already_clarified=already_clarified,
                )
                if question:
                    self._clarified = True

                    # 幻覺偵測路徑：跑 multi-market 查詢，組真實候選清單
                    if is_multi_market_trigger(question):
                        ticker_or_query = self._extract_clarify_target(raw_query)
                        logger.info(
                            "[ClawLoop] multi-market clarification triggered for %r "
                            "(hallucination detected, used_tools=[])",
                            ticker_or_query,
                        )
                        final_question = self._build_multi_market_question(
                            ticker_or_query, language
                        )
                    else:
                        # 既有路徑：直接用 should_clarify 回的字串
                        logger.info(
                            "[ClawLoop] progressive clarification triggered for %r",
                            raw_query[:30],
                        )
                        final_question = question

                    return {
                        "final_response": final_question,
                        "_processed_query": raw_query,
                        "_needs_clarification": True,
                    }
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.warning(f"[ClawLoop] clarification check failed: {e}")

        # 進入「無有效回應」處理的條件：response 空 OR agent 明確失敗。
        # 關鍵（同 #309 bug 模式）：agent 失敗時 result.message 是
        # empty_response_message（26字錯誤訊息，非空），若只看 `not response`
        # 會誤判「有回應」→ clarify / fallback 整個被跳過。
        _agent_failed = not getattr(result, "success", True)
        if not response or _agent_failed:
            # ============================================================
            # Phase D：Vague-Query Clarify（學 Hermes clarify，複用 consent gate 模式）
            #
            # 當模型面對模糊綜合判斷問題（如「美股適合買嗎」——非特定 ticker）
            # 時困惑回空，不直接放棄，而是向使用者釐清意圖。interrupt 暫停 graph，
            # 使用者答後 Command(resume) 從 node 開頭重跑，此 flag（state，非 self）
            # 防無限觸發。
            #
            # 與 Phase C 的 should_clarify 不同：Phase C 要求 response 非空
            # （LLM 回了「查無」）；本相位處理 response 完全空（LLM 放棄）。
            # ============================================================
            _vague_clarified = bool(state.get("_vague_clarified", False))
            if not _vague_clarified:
                try:
                    from langgraph.types import interrupt

                    from core.agents.base_react_agent import empty_response_message
                    from core.agents.clarification import should_clarify_vague_query

                    clarify_payload = await should_clarify_vague_query(
                        query=raw_query,
                        # 關鍵：當 agent 失敗時 result.message 是 empty_response_message
                        # （26字錯誤訊息，非空），但那不是真正回應。傳給 should_clarify
                        # 時要當作空，否則它判斷「response 非空 → 不是 vague-empty」
                        # → return None → clarify 永遠不觸發（同 #309 的 bug 模式）。
                        response=(
                            ""
                            if (
                                not getattr(result, "success", True)
                                or response == empty_response_message(language)
                            )
                            else response
                        ),
                        already_clarified=_vague_clarified,
                        language=language,
                        llm=self.llm,
                    )
                    if clarify_payload:
                        logger.info(
                            "[ClawLoop] vague-query clarify triggered for %r "
                            "(empty response, no ticker)",
                            raw_query[:30],
                        )
                        # interrupt 暫停 graph；使用者答後 resume 從 node 開頭重跑。
                        # 用 state _vague_clarified 防 resume 時無限重觸發。
                        clarify_answer = interrupt(clarify_payload)
                        # resume 回到此處：把使用者釐清答案 prepend 進 query 重跑 LLM
                        raw_query = (
                            f"{clarify_answer}\n\n（使用者補充釐清）原問題：{raw_query}"
                        )
                        # 重跑 agent（帶釐清後的 query）
                        clarified_task = SubTask(
                            step=task.step + 1,
                            description=raw_query,
                            agent=task.agent,
                            context=task.context,
                        )
                        result = await _run_agent(clarified_task)
                        _flush_stream_sanitizer()
                        response = _clean_claw_response(result.message)
                        return {
                            "final_response": response
                            or empty_response_message(language),
                            "_processed_query": raw_query,
                            "_vague_clarified": True,
                        }
                except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                    raise
                except GraphInterrupt:
                    # interrupt() 拋 GraphInterrupt 暫停 graph — 正常 control-flow，
                    # 必須原樣上拋（同 consent gate line 954），否則被下方 except 吞。
                    raise
                except Exception as e:
                    logger.warning(
                        f"[ClawLoop] vague-query clarify 故障（非致命）: {e}"
                    )

            # ============================================================
            # BYOK Fallback Provider Chain（預設停用）
            #
            # 當所有 recovery 用完、user 的 BYOK 模型還是生不出答案時，
            # 用 server-side 預設模型再跑一次。涉及 server 成本，預設關閉，
            # 需 BYOK_FALLBACK_ENABLED=true + 完整 env 才啟用（DANNY 確認）。
            # 詳見 core/agents/fallback.py。
            #
            # 2026-07-19 強化：
            # - 加 FALLBACK_TIMEOUT_SECONDS=30 上限（Hermes #12770 教訓：
            #   cascade fallback 易浪費 20-60s，超過就放棄走既有 fallback msg）
            # - fallback client 用較小 max_tokens=6144（避免 402）
            # ============================================================
            try:
                from core.agents.fallback import (
                    FALLBACK_TIMEOUT_SECONDS,
                    get_fallback_client,
                    should_fallback,
                )

                if should_fallback(
                    final_response=response,
                    used_tools=used_tools,
                    retry_exhausted=True,
                ):
                    fallback_client = get_fallback_client()
                    if fallback_client is not None:
                        logger.info(
                            "[ClawLoop] BYOK 模型失敗，啟用 fallback provider"
                        )
                        # 記錄 fallback 計數（turn-scoped + cascade 防護）
                        try:
                            from core.agents.fallback import mark_fallback_used

                            mark_fallback_used()
                        except Exception:
                            pass
                        # 延遲 import 避免循環依賴
                        from langgraph.types import Command

                        from core.agents.bootstrap import bootstrap

                        # G4 修復：bootstrap() 是同步函式（內部做 PromptRegistry.load、
                        # skill yaml 載入等 sync file I/O），在 async node 內直接呼叫
                        # 會阻塞 event loop（違反 AGENTS.md 規範）。走 run_sync bridge。
                        # 見既有 line 341 check_idle_consolidation 也是同樣處理。
                        from core.agents.manager import MANAGER_GRAPH_RECURSION_LIMIT

                        def _do_fallback_bootstrap():
                            return bootstrap(
                                fallback_client,
                                web_mode=True,
                                language=language,
                                user_tier=self.user_tier,
                                user_id=self.user_id,
                                session_id=f"{self.session_id}-fb",
                                key_fingerprint="fallback",
                            )

                        fb_manager = await run_sync(_do_fallback_bootstrap)

                        # G5 修復：recursion_limit 是 LangGraph 的「step count」，
                        # 不是秒。過去誤用 timeout 秒數當 step limit 會讓 graph
                        # 可遞迴異常多步。改用 MANAGER_GRAPH_RECURSION_LIMIT。
                        fb_config = {
                            "configurable": {"thread_id": f"{self.session_id}-fb"},
                            "recursion_limit": MANAGER_GRAPH_RECURSION_LIMIT,
                        }
                        fb_input = Command(
                            goto="claw_loop",
                            update={
                                "session_id": f"{self.session_id}-fb",
                                "query": raw_query,
                                "history": history,
                                "history_load_status": "loaded" if history else "empty",
                                "history_truncated": False,
                                "history_token_count": len(history) // 4,
                                "history_message_count": 0,
                                "system_prompt": "",
                                "enabled_tools": [],
                                "task_results": {},
                                "language": language,
                                "execution_mode": "vending",
                            },
                        )
                        # fallback_used 已在 _claw_loop_node 開頭初始化為 False（G3），
                        # 這裡不再重設——避免誤以為還有殘留邏輯。
                        try:
                            # 30s 硬上限：避免 Hermes #12770 的 cascade 浪費
                            fb_result = await asyncio.wait_for(
                                fb_manager.graph.ainvoke(fb_input, fb_config),
                                timeout=FALLBACK_TIMEOUT_SECONDS,
                            )
                            fb_response = (
                                fb_result.get("final_response")
                                if isinstance(fb_result, dict)
                                else None
                            )
                            if fb_response and _clean_claw_response(fb_response):
                                response = (
                                    f"[fallback] {_clean_claw_response(fb_response)}"
                                )
                                fallback_used = True
                                logger.info(
                                    "[ClawLoop] fallback 成功，使用 fallback 回應"
                                )
                        except asyncio.TimeoutError:
                            logger.warning(
                                f"[ClawLoop] fallback provider 超過 "
                                f"{FALLBACK_TIMEOUT_SECONDS}s，放棄 fallback"
                            )
                        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                            raise
                        except Exception as fb_exc:
                            logger.warning(
                                f"[ClawLoop] fallback provider 也失敗: {fb_exc}"
                            )
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.warning(f"[ClawLoop] fallback chain 評估失敗: {e}")

        # ============================================================
        # Phase E：Wrong-Scope Clarify（非空但答錯範圍，複用 Phase D 模式）
        #
        # 場景（截圖鐵證）：使用者問「台股是否值得投資」（範圍問題，標的未確定），
        # 中等模型直接答「台積電（2330）…」（偷換成特定股）；或問「我想要投資」，
        # 模型被前文 context 帶偏調加密貨幣工具。兩者都是「非空、成功、但答非所問」。
        #
        # Phase C（查無）與 Phase D（空回應）都抓不到這類。Phase E 用
        # should_clarify_wrong_scope 偵測「query 是範圍問題 + response 跳到 query
        # 沒提的具體 ticker + response 缺廣度詞彙」，觸發 interrupt 向使用者釐清，
        # 答後 resume 從 node 開頭重跑（state _scope_clarified 防 resume 無限觸發）。
        #
        # 插入點選在 fallback chain 之後、`if not response:` 之前：此時 response
        # 已最終定案（過了 Phase C/D/fallback），是最後乾淨攔截點；且此處 response
        # 一定非空（空的已被上方 `if not response or _agent_failed:` 區塊處理）。
        # ============================================================
        _scope_clarified = bool(state.get("_scope_clarified", False))
        if (
            not _scope_clarified
            and response
            and getattr(result, "success", True)
        ):
            try:
                from langgraph.types import interrupt

                from core.agents.base_react_agent import empty_response_message
                from core.agents.clarification import should_clarify_wrong_scope

                clarify_payload = await should_clarify_wrong_scope(
                    query=raw_query,
                    response=response,
                    used_tools=used_tools,
                    already_clarified=_scope_clarified,
                    language=language,
                    llm=self.llm,
                )
                if clarify_payload:
                    logger.info(
                        "[ClawLoop] wrong-scope clarify triggered for %r "
                        "(non-empty response answered wrong scope)",
                        raw_query[:30],
                    )
                    # interrupt 暫停 graph；使用者答後 resume 從 node 開頭重跑。
                    # 用 state _scope_clarified 防 resume 時無限重觸發（同 Phase D）。
                    clarify_answer = interrupt(clarify_payload)
                    # resume 回到此處：把使用者釐清答案 prepend 進 query 重跑 LLM
                    raw_query = (
                        f"{clarify_answer}\n\n（使用者補充釐清）原問題：{raw_query}"
                    )
                    scope_task = SubTask(
                        step=task.step + 1,
                        description=raw_query,
                        agent=task.agent,
                        context=task.context,
                    )
                    result = await _run_agent(scope_task)
                    _flush_stream_sanitizer()
                    response = _clean_claw_response(result.message)
                    return {
                        "final_response": response
                        or empty_response_message(language),
                        "_processed_query": raw_query,
                        "_scope_clarified": True,
                    }
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except GraphInterrupt:
                # interrupt() 拋 GraphInterrupt 暫停 graph — 正常 control-flow，
                # 必須原樣上拋（同 Phase D line 1295），否則被 except Exception 吞。
                raise
            except Exception as e:
                logger.warning(
                    f"[ClawLoop] wrong-scope clarify 故障（非致命）: {e}"
                )

        # ============================================================
        # Phase F：Model-Driven Clarify（hybrid：模型呼叫 clarify 工具,node 攔截）
        #
        # Hermes 式 model-driven 釐清——強模型(Claude/GPT)判斷問題範圍/標的不明確時，
        # 主動呼叫 clarify 工具。工具回傳 {"__needs_clarify__": True, ...} 訊號
        # （自己不 interrupt，因為純 tool-level interrupt 在本 codebase 不可行——
        # 內層 agent 沒 checkpointer）。本相位偵測 used_tools 含 "clarify"，
        # 由已驗證的 node-level interrupt() 接手（接收器零改動）。
        #
        # 與 Phase E(rule 後衛)互補：
        # - Phase E：模型答錯範圍 → 程式被動攔截（弱模型用）
        # - Phase F：模型主動呼叫 clarify 工具 → 程式偵測訊號接手（強模型用）
        # 兩層獨立，雙保險。
        # ============================================================
        _tool_clarified = bool(state.get("_tool_clarified", False))
        if not _tool_clarified and "clarify" in used_tools:
            clarify_signal = _extract_clarify_signal(
                result.data if isinstance(result.data, dict) else {}
            )
            if clarify_signal and clarify_signal.get("question"):
                try:
                    from langgraph.types import interrupt

                    from core.agents.base_react_agent import empty_response_message

                    logger.info(
                        "[ClawLoop] model-driven clarify triggered for %r "
                        "(model called clarify tool)",
                        raw_query[:30],
                    )
                    # 組 payload（同 Phase D/E 的 clarify 卡格式，前端零改動）
                    clarify_payload = {
                        "type": "clarify",
                        "question": clarify_signal["question"],
                    }
                    if clarify_signal.get("options"):
                        clarify_payload["options"] = [
                            {"label": o, "hint": o} if isinstance(o, str) else o
                            for o in clarify_signal["options"]
                        ]
                        clarify_payload["select_mode"] = "single"
                    # interrupt 暫停 graph；使用者答後 resume 從 node 開頭重跑。
                    # 用 state _tool_clarified 防 resume 時無限重觸發（同 Phase D/E）。
                    clarify_answer = interrupt(clarify_payload)
                    # resume 回到此處：把使用者釐清答案 prepend 進 query 重跑 LLM
                    raw_query = (
                        f"{clarify_answer}\n\n（使用者補充釐清）原問題：{raw_query}"
                    )
                    tool_clarified_task = SubTask(
                        step=task.step + 1,
                        description=raw_query,
                        agent=task.agent,
                        context=task.context,
                    )
                    result = await _run_agent(tool_clarified_task)
                    _flush_stream_sanitizer()
                    response = _clean_claw_response(result.message)
                    return {
                        "final_response": response
                        or empty_response_message(language),
                        "_processed_query": raw_query,
                        "_tool_clarified": True,
                    }
                except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                    raise
                except GraphInterrupt:
                    # interrupt() 拋 GraphInterrupt 暫停 graph — 正常 control-flow，
                    # 必須原樣上拋（同 Phase D/E line 1295/1499），否則被 except 吞。
                    raise
                except Exception as e:
                    logger.warning(
                        f"[ClawLoop] model-driven clarify 故障（非致命）: {e}"
                    )

        if not response:
            response = _no_valid_result_message(
                getattr(self, "language", "zh-TW")
            )
        elif not fallback_used:
            # G3 修復：截斷偵測只該在「主 agent 的 response」上跑。
            # 若 response 來自 fallback（[fallback] prefix），主 agent 的 result.data
            # 是失敗那輪的（finish_reason 可能是 None 或錯的），不該拿來偵測。
            # fallback 自己的 fb_result 是 dict（不是 AgentResult），沒 finish_reason
            # 欄位——先不對 fallback 做 finish_reason 偵測（fallback 路徑少見，
            # 且 6144 token 通常夠用）。
            result_data_for_truncation = (
                result.data if isinstance(result.data, dict) else {}
            )
            response = _detect_and_annotate_truncation(
                response, result_data_for_truncation, language
            )

        await self._track_conversation(
            user_message=raw_query,
            assistant_response=response,
            tools_used=used_tools,
        )
        self._invoke_response_hooks(state, response)
        logger.info(f"[ClawLoop] done, used_tools={used_tools}")

        # ── Phase D：詐騙判定證據鏈（Trustworthy AI HITL，場景 B 輕量版）──
        # ============================================================
        # Phase G：Skill / Memory 自主管理 HITL consent
        # (docs/plans/2026-08-10-agent-self-managed-skills-memory-design.md)
        #
        # 工具（remember / propose_custom_skill）回傳 __needs_consent__ marker，
        # 不直接寫 DB。本相位偵測 marker → interrupt() 暫停顯示同意卡 →
        # 使用者核准後才寫入 SkillPreferenceStore / MemoryStore。
        # 仿 Phase F clarify 的 marker 攔截模式（工具不能自己 interrupt，
        # 因為內層 agent 沒 checkpointer）。
        #
        # 安全不變量：
        # - user_id 從 self.user_id（JWT/session）讀，不從 marker 讀——
        #   prompt injection 無法指定寫到別人帳號。
        # - 改/刪前先撈 before 快照，記進 audit log（事後追溯）。
        # - state _handled_consent_ts 防同一 marker 在 resume 重入時重複彈卡
        #   （2026-08-22 修：原 _skill_consent_done 永久 flag 讓「同一 session
        #   第二次記帳/記憶」永遠不彈卡——改比對 marker 的唯一 ts）。
        # ============================================================
        _skill_consent_done = bool(state.get("_skill_consent_done", False))
        # 直接從 result.data 的 tool_outputs 抽 marker（權威訊號），不依賴
        # used_tools 收集。base_react_agent 的 used_tools 從 ToolMessage.name
        # 收集，與 wrap_tool audit 層的實際呼叫記錄可能不一致（部分 provider
        # 的 ToolMessage.name 缺失或為空），導致 used_tools 漏記 → 舊邏輯會
        # 在這裡 short-circuit 跳過 Phase G，consent 卡永遠不彈出。
        # marker 是工具自己產生的權威訊號，比 used_tools 收集可靠。
        #
        # 多卡批次（2026-08-25）：一輪可能有多個提案（記帳＋刪記憶＋增記憶…）。
        # 舊版只取第一個 marker → 只彈第一張卡、其餘靜默丟失。現在：
        # - 單一 pending 且屬既有 kind → 走原單卡豐富 UI（行為完全不變）
        # - 多個 pending（或 journal_delete/update）→ multi_consent 批次卡：
        #   一次 interrupt、前端一次顯示全部、一次 resume 帶回答案陣列。
        #
        # ⚠️ 不做跨 turn 的 state 去重（2026-08-25 線上事故教訓）：曾把已作答
        # 提案的 identity 存進 state——使用者「未答的子卡＝deny」一次之後，
        # 同一提案在整個 session 永遠不再彈卡（#27 卡死案例）。resume 重跑的
        # 重複提案由 LangGraph interrupt 的索引匹配自然消化（resume 的答案
        # 會被第一個 interrupt() 呼叫取回，不會重彈）；這裡只對「同一次
        # 執行內」的重複 identity 去重（同一提案在 tool_outputs 出現兩次只
        # 顯示一張卡）。
        _handled_any_no_ts = False  # 舊式無 ts marker → 沿用永久 flag 防重彈
        if not _skill_consent_done:
            all_signals = _extract_consent_signals(
                result.data if isinstance(result.data, dict) else {}
            )
            pending = []
            _seen = set()
            for s in all_signals:
                ident = _consent_identity(s)
                if ident in _seen:
                    continue
                _seen.add(ident)
                pending.append(s)

            if pending:
                try:
                    from langgraph.types import interrupt

                    from core.agents.manager.consent_gate import (
                        append_guard_audit_receipt,
                        build_journal_consent_payload,
                        build_memory_consent_payload,
                        build_skill_consent_payload,
                        log_journal_entry_decision,
                        log_skill_memory_decision,
                        parse_skill_memory_consent_answer,
                    )

                    language = getattr(self, "language", "zh-TW")
                    uid = getattr(self, "user_id", None)
                    uname = getattr(self, "display_name", None)

                    async def _audit(kind: str, approved: bool, mode: str, batch: bool):
                        """寫 guard audit receipt——失敗只警告，絕不擋套用。

                        線上教訓（2026-08-25）：audit 與套用包在同一個 try 裡，
                        audit 炸（worker 跨 loop）會把使用者核准的動作一起吃掉。
                        """
                        try:
                            await append_guard_audit_receipt(
                                user_id=uid,
                                event_type=(
                                    "agent.journal_consent"
                                    if kind.startswith("journal")
                                    else "agent.skill_memory_consent"
                                ),
                                payload={
                                    "approved": approved,
                                    "kind": kind,
                                    "mode": mode,
                                    **({"batch": True} if batch else {}),
                                },
                            )
                        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                            raise
                        except Exception as exc:
                            logger.warning(
                                "[ClawLoop] consent audit receipt 失敗（不擋套用）: %s", exc
                            )

                    async def _apply(uid_, signal_, edited_):
                        """run_sync 包同步 DB 寫入（凍結 event loop 防護），失敗只警告。"""
                        try:
                            return await run_sync(_apply_consent_write, uid_, signal_, edited_)
                        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                            raise
                        except Exception as exc:
                            logger.warning(
                                "[ClawLoop] consent apply 失敗 kind=%s: %s",
                                signal_.get("kind"), exc,
                            )
                            return None

                    use_single = (
                        len(pending) == 1
                        and pending[0].get("kind", "") in _SINGLE_CARD_KINDS
                    )
                    if use_single:
                        signal = pending[0]
                        kind = signal.get("kind", "")

                        if kind in ("create_memory", "delete_memory"):
                            payload = build_memory_consent_payload(signal, language)
                        elif kind == "journal_entry":
                            payload = build_journal_consent_payload(signal, language)
                        else:
                            payload = build_skill_consent_payload(signal, language)

                        answer = interrupt(payload)  # pauses graph; resume lands here
                        parsed = parse_skill_memory_consent_answer(answer)
                        approved = parsed["approved"]
                        edited = parsed.get("edited_fields") or {}

                        await _audit(kind, approved, signal.get("mode", "create"), batch=False)

                        if approved:
                            # 使用者可能用「先編輯再核准」改了內容——以 edited 覆蓋。
                            entry_id = await _apply(uid, signal, edited)
                        else:
                            entry_id = None
                        try:
                            if kind == "journal_entry":
                                log_journal_entry_decision(
                                    user_id=uid,
                                    username=uname,
                                    approved=approved,
                                    signal=signal,
                                    edited=edited,
                                    entry_id=entry_id,
                                )
                            else:
                                log_skill_memory_decision(
                                    user_id=uid,
                                    username=uname,
                                    kind=kind,
                                    mode=signal.get("mode", "create"),
                                    approved=approved,
                                    after=({**signal, **edited} if approved else None),
                                )
                        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                            raise
                        except Exception as exc:
                            logger.warning("[ClawLoop] consent audit log 失敗: %s", exc)
                        if not signal.get("ts"):
                            _handled_any_no_ts = True
                    else:
                        # ── multi_consent 批次：一次 interrupt 顯示全部 pending ──
                        payload = build_multi_consent_payload(pending, language)
                        answers_raw = interrupt(payload)  # resume 帶回答案陣列
                        answers = parse_multi_consent_answers(
                            answers_raw, expected=len(pending)
                        )

                        for signal, parsed in zip(pending, answers):
                            kind = signal.get("kind", "")
                            approved = parsed["approved"]
                            edited = parsed.get("edited_fields") or {}

                            await _audit(kind, approved, signal.get("mode", ""), batch=True)

                            entry_id = None
                            if approved:
                                entry_id = await _apply(uid, signal, edited)
                            try:
                                if kind == "journal_entry":
                                    log_journal_entry_decision(
                                        user_id=uid,
                                        username=uname,
                                        approved=approved,
                                        signal=signal,
                                        edited=edited,
                                        entry_id=entry_id,
                                    )
                                else:
                                    log_skill_memory_decision(
                                        user_id=uid,
                                        username=uname,
                                        kind=kind,
                                        mode=signal.get("mode", ""),
                                        approved=approved,
                                        before=signal.get("before") if kind in (
                                            "journal_delete", "journal_update"
                                        ) else None,
                                        after=({**signal, **edited} if approved else None),
                                    )
                            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                                raise
                            except Exception as exc:
                                logger.warning("[ClawLoop] consent audit log 失敗: %s", exc)
                            if not signal.get("ts"):
                                _handled_any_no_ts = True
                except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                    raise
                except GraphInterrupt:
                    # interrupt() 拋 GraphInterrupt 暫停 graph — 正常 control-flow，
                    # 必須原樣上拋（同 Phase D/E/F），否則被 except Exception 吞。
                    raise
                except Exception as exc:
                    logger.warning(
                        "[ClawLoop] skill/memory consent 故障（非致命）: %s", exc
                    )

        # 不用 LangGraph interrupt。偵測「用了 GoPlus 詐騙判定工具」→ 取側錄的
        # raw info → _extract_risk_signals + risk_scoring → 組 scam_evidence。
        # 只在 verdict 屬高關注等級時附上（normal/insufficient 不顯示卡片）。
        # 證據鏈由後端附加，不改 LLM 看到的工具輸出（markdown 保留）。
        scam_evidence = _build_scam_evidence(used_tools)

        # 平台完全退出交換鏈路：Agent 是「分析地址/代幣/支付風險的唯讀安全助手」，

        return {
            "final_response": response,
            "_processed_query": raw_query,
            "scam_evidence": scam_evidence,
            # 舊式（無 ts）marker 沿用永久 flag 防 resume 無限重彈；新式 marker
            # 不鎖死——下一輪使用者再要求，提案會重新彈卡（#27 卡死事故修正）。
            "_skill_consent_done": (
                True if _skill_consent_done else _handled_any_no_ts
            ),
        }
