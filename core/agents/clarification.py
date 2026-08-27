"""
Progressive Clarification — 模糊情境時主動問使用者（學 LangGraph HITL）。

SNXX 場景：LLM 看到「SNXX」不確定是加密貨幣還是美股 ETF。正確行為是
**問使用者**「您指的 SNXX 是加密貨幣還是美股？」，而不是直接猜成加密貨幣。

設計原則
--------
- **保守觸發**：每個 session 最多觸發 1 次 clarification（避免無限追問）
- **只在真模糊時觸發**：不是所有未知代號都該問（有些 LLM 該自己查）
- **走既有 HITL 機制**：analysis.py 已支援 Command(resume=...)，
  clarification 結果用特殊 final_response 格式，前端顯示為追問氣泡

觸發條件（AND 全滿足才觸發）
----------------------------
1. LLM 回應含「不確定 / 查無 / 找不到」+ 沒用任何工具
2. 或 resolve_symbol 失敗（symbol=null）+ 沒 fallback 到其他市場
3. 該 session 還沒觸發過 clarification
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# 「不確定 / 查無」的多語 pattern
# 用來判斷 LLM 是否「放棄了」而不是「找到了」
_UNCERTAINTY_PATTERNS = [
    # zh-TW / zh-CN
    r"查無",
    r"找不到",
    r"不確定",
    r"無法確認",
    r"無法確定",
    r"可能是.*但.*不確定",
    r"暫時無法",
    r"暂时无法",
    r"未能確認",
    r"未能确认",
    r"查不到",
    r"沒有找到",
    r"没有找到",
    # en
    r"\bcannot (?:find|determine|confirm)\b",
    r"\bunable to (?:find|determine)\b",
    r"\bnot sure\b",
    r"\bcould not (?:find|resolve)\b",
    r"\bno (?:data|results?|match) (?:found|available)\b",
    # ru
    r"не удалось",
    r"не могу (?:найти|определить)",
    r"не уверен",
]
_UNCERTAINTY_RE = re.compile(
    "|".join(_UNCERTAINTY_PATTERNS), re.IGNORECASE
)


# ============================================================================
# 幻覺偵測（2026-07-20 新增 — AKE 案例）
#
# LLM 沒呼叫工具卻生成「正在獲取即時價格...」「RSI 分析...」這類假動作訊息，
# 讓使用者誤以為 agent 正在查資料。實際上是模型在編造內容。
#
# 這些 pattern 抓「進行式動作詞」+「即時數據」但沒實際 tool 引用：
# ============================================================================
_FAKE_ACTION_PATTERNS = [
    # zh-TW / zh-CN — 「正在 X」進行式
    r"正在獲取",
    r"正在取得",
    r"正在查詢",
    r"正在計算",
    r"正在抓取",
    r"正在讀取",
    r"正在為您整理",
    r"正在分析",
    r"正在為您",
    r"資料載入中",
    r"查詢中\.\.\.",
    r"請稍候.*查詢",
    r"請稍候.*獲取",
    r"即時獲取",
    r"實時獲取",
    # en — present continuous fake actions
    r"\bfetching\b.*\b(?:price|data|rate)\b",
    r"\bcalculating\b.*\b(?:rate|return|roi|change)\b",
    r"\bcomputing\b.*\b(?:rate|change|indicator)\b",
    r"\bretrieving\b.*\b(?:price|data|standby)\b",
    r"\blooking up\b.*\b(?:please wait|standby)\b",
    # ru
    r"получаю.*данные",
    r"запрашиваю.*цен",
    r"вычисляю",
]
_FAKE_ACTION_RE = re.compile("|".join(_FAKE_ACTION_PATTERNS), re.IGNORECASE)

# 代號模式（大寫字母 + 可選數字，2-6 字元）
_TICKER_RE = re.compile(r"\b[A-Z]{2,6}\d?\b")

# 「查無此幣 / 查無此代號」明確失敗模式
_EXPLICIT_NOT_FOUND_PATTERNS = [
    r"查無.*幣",
    r"查無.*代號",
    r"找不到.*(?:幣|代號|標的|資產)",
    r"沒有.*名為",
    r"no.*(?:coin|token|ticker|symbol|asset).*found",
    r"cannot.*find.*(?:coin|token|ticker|symbol)",
]
_EXPLICIT_NOT_FOUND_RE = re.compile(
    "|".join(_EXPLICIT_NOT_FOUND_PATTERNS), re.IGNORECASE
)


def _detect_query_ticker(query: str) -> Optional[str]:
    """從 user query 中偵測可能的代號（大寫英文 2-6 字元）。"""
    if not query:
        return None
    matches = _TICKER_RE.findall(query)
    # 過濾已知加密貨幣（從 company_aliases.json 派生，單一真相來源）。
    # 已知 crypto 是明確標的，不需要 clarify。
    known_crypto = _known_crypto_symbols()
    for m in matches:
        if m not in known_crypto:
            return m
    return None


async def should_clarify_vague_query(
    query: str,
    response: str,
    already_clarified: bool = False,
    language: str = "zh-TW",
    llm=None,
) -> Optional[dict]:
    """偵測「模型困惑回空」的模糊問題，回傳 clarify payload（向使用者釐清）。

    與既有 should_clarify 不同：should_clarify 處理「response 非空但含『查無』」
    （LLM 自己承認找不到）；本函式處理「response 空 + 無特定 ticker」——
    模型面對「美股適合買嗎」這種模糊綜合判斷問題，既不敢答（怕幻覺）又
    無特定 ticker 可查，於是回空。此時應向使用者釐清意圖（學 Hermes clarify）。

    Args:
        query: 使用者原始問題。
        response: LLM 最終回應（空字串 = 模型放棄）。
        already_clarified: 該請求是否已 clarify 過（防無限追問）。
        language: 語言。

    Returns:
        dict {type: "clarify", question: <釐清問題>} 或 None（不需 clarify）。

    觸發條件（全部滿足）：
    1. 已 clarify 過 → 不再觸發（防無限迴圈）
    2. response 空（模型放棄/困惑）
    3. query 無特定 ticker（不是「BTC」「台積電」這種明確標的）
       → 有明確 ticker 的空回覆屬於 should_clarify 路徑（查無此標的）
    4. query 有實質內容（不是純閒聊「你好」那種，閒聊不會走到這裡）
    """
    if already_clarified:
        return None
    if response and response.strip():
        return None  # 有回應 → 不是 vague-empty 場景
    if not query or len(query.strip()) < 4:
        return None  # 太短不像需要釐清的問題
    # Skill / memory 管理意圖（「我有哪些 skill」「列出分析方法」「刪除 skill」…）
    # 不是投資問題，不該走投資導向的 clarify fallback（會誤彈「整體大盤/特定股票」
    # 選項）。讓 agent 正常跑——system prompt 的 self_manage_skills 段落會教它呼叫
    # list_my_skills_memory / propose_custom_skill。
    if _SKILL_MEMORY_INTENT_RE.search(query):
        return None
    if _detect_query_ticker(query):
        return None  # 有英文代號 ticker → 走既有 should_clarify（查無此標的）
    # 中文標的名稱（特斯拉/台積電/蘋果/輝達/比特幣…）也是明確標的，不算模糊問題。
    # _detect_query_ticker 只認大寫英文代號（AAPL/BTC），漏掉中文名 →
    # 「特斯拉現在真的值得購買嗎」被誤判為模糊綜合判斷問題、觸發 false-positive
    # 釐清（線上 #特斯拉案例）。用 _extract_tickers_zh 補上中文標的偵測；
    # 這裡要 include_crypto=True——對 query 側而言，加密貨幣也是明確標的
    # （「比特幣值得買嗎」不該再問「你指什麼」）。
    if _extract_tickers_zh(query, include_crypto=True):
        return None

    # 組釐清問題：基於 query 推測可能的意圖方向（有 LLM 時動態生成選項）
    question, options = await _build_vague_query_clarification(query, language, llm=llm)
    payload: dict = {"type": "clarify", "question": question}
    if options:
        # 結構化選項（學 Hermes clarify 的 single-select MC + Other）。
        # 前端可渲染可點選按鈕；options 為空時退回純文字輸入。
        payload["options"] = options
        payload["select_mode"] = "single"  # single | multi
    return payload


async def _build_vague_query_clarification(
    query: str, language: str = "zh-TW", llm=None
) -> tuple[str, list[dict]]:
    """為模糊問題組釐清提示 + 結構化選項。

    學 Hermes clarify：最多 4 選項 + 隱含「Other」（前端自由輸入）。
    不猜測答案，而是列出可能的方向讓使用者選/補充。

    LLM 動態選項（混合策略，2026-08）：
    - 規則負責「是否觸發」；選項由 LLM 依 query 語意動態生成（2-4 個），
      解決「所有模糊問題都彈同一組投資導向選項」的脫節問題。
    - llm 為 None / 生成失敗 / 格式不合法 → fallback 到寫死選項（行為不變）。

    Args:
        query: 使用者原始問題。
        language: UI 語言（zh-TW / zh-CN / en / ru）。
        llm: 可選 LLM 實例（LangChain 相容，需有 ainvoke/invoke）。

    Returns:
        (question_text, options)：options 每項 {label, hint}，label 是選項文字、
        hint 是選了之後系統會帶入重跑的補充說明。
    """
    if language == "en":
        question = (
            f"I'm not sure what you mean by \"{query}\". "
            "Could you clarify? Pick one or type your own:"
        )
        # 投資意圖才給投資選項；否則給中性通用選項（避免非投資查詢被投資選項誤導）。
        if _INVESTMENT_INTENT_RE.search(query):
            fallback_options = [
                {"label": "Overall market (S&P 500, Dow)", "hint": "the overall US market index like S&P 500 or Dow Jones"},
                {"label": "A specific stock", "hint": "a specific stock (please specify ticker like AAPL, TSLA)"},
                {"label": "A sector / industry", "hint": "a specific sector or industry like tech, energy"},
                {"label": "Technical vs fundamental judgment", "hint": "whether it's a good time to enter, based on technical and fundamental view"},
            ]
        else:
            fallback_options = [
                {"label": "Rephrase the question", "hint": "I'll describe what I want more concretely"},
                {"label": "Give a specific target", "hint": "I'll provide a specific name, ticker, or subject"},
                {"label": "Ask differently", "hint": "I'll try another way to ask"},
            ]
    else:
        # zh-TW / zh-CN 共用（簡繁差異不影響理解）
        question = f"我不太確定你問的「{query}」具體指什麼，可以幫我釐清一下嗎？選一個或自己輸入："
        if _INVESTMENT_INTENT_RE.search(query):
            fallback_options = [
                {"label": "整體大盤（S&P 500、道瓊）", "hint": "美股整體大盤指數，如 S&P 500 或道瓊"},
                {"label": "特定股票", "hint": "某支特定股票（請補充股票名或代號，如蘋果/AAPL）"},
                {"label": "某個產業／板塊", "hint": "某個產業或板塊，如科技、能源、金融"},
                {"label": "值不值得進場的整體判斷", "hint": "現在是否適合進場的技術面 + 基本面綜合判斷"},
            ]
        else:
            fallback_options = [
                {"label": "重新描述問題", "hint": "我會更具體地描述我想問什麼"},
                {"label": "給具體標的", "hint": "我會補充明確的名稱、代號或主題"},
                {"label": "換個問法", "hint": "我會用另一個方式問"},
            ]

    # LLM 動態生成選項（混合策略）。失敗一律 fallback 寫死，不影響主流程。
    if llm is not None:
        try:
            generated = await _generate_clarify_options_via_llm(query, language, llm)
            if generated:
                return question, generated
        except Exception as e:  # noqa: BLE001 — fallback 設計，任何失敗都退回寫死
            logger.warning(f"[Clarify] LLM option generation failed, using fallback: {e}")
    return question, fallback_options


async def _generate_clarify_options_via_llm(
    query: str, language: str, llm
) -> Optional[list[dict]]:
    """用 LLM 依 query 語意生成 2-4 個釐清選項（{label, hint}）。

    失敗（例外 / 非 JSON / 選項數不符 / 欄位缺）回 None，由呼叫端 fallback。

    deepseek / OpenAI 相容 provider 實測不穩定遵守「只回傳 JSON」的 system
    指令（常回傳排版精美的中文長文而非 JSON）→ 優先帶 response_format
    json_object 強制 JSON；不支援該參數的 provider（anthropic/gemini 等）
    拋例外時自動退回不帶 format 再試一次。
    """
    # zh-TW/zh-CN 共用同一份中文 JSON 指令；en/ru 各自本地化。
    # 注意：fallback 必須是「指令內容」而非字面 "zh-CN"——早期 bug 是
    # `.get(language, "zh-CN")` 把字串 "zh-CN" 當 fallback 塞進 prompt，
    # 導致 prompt 不含 "json" 字樣 → deepseek json_object mode 400。
    zh_json_instruction = (
        "只回傳 JSON 陣列，2-4 個物件，每個含 \"label\"（選項文字，<=20 字）"
        "與 \"hint\"（選了會做什麼，<=40 字）。不要 markdown、不要其他文字。"
    )
    lang_instruction = {
        "en": "Respond ONLY with a JSON array of 2-4 objects, each with "
              '"label" (short option text, <=20 chars) and "hint" '
              '(what will happen if chosen, <=40 chars). No markdown, no commentary.',
        "zh-CN": zh_json_instruction,
        "zh-TW": zh_json_instruction,
        "ru": "Ответь ТОЛЬКО JSON-массивом из 2-4 объектов с полями "
              '"label" (короткий текст, <=20 символов) и "hint" '
              '(что будет после выбора, <=40 символов). Без markdown и комментариев.',
    }.get(language, zh_json_instruction)

    prompt = (
        f"User asked a vague question: \"{query}\".\n"
        "The assistant cannot determine the specific target. "
        "Generate 2-4 clarification options that cover the most likely directions "
        "the user might mean. Options must be concrete, distinct, and match the "
        "question's actual ambiguity (e.g. which market, which asset class, "
        "price vs technical analysis vs safety check). "
        f"{lang_instruction}"
    )

    # 第一優先：response_format=json_object（deepseek/OpenAI 相容）；
    # 失敗（provider 不支援拋例外 / 回覆仍無法解析）→ 不帶 format 再試一次。
    #
    # 關鍵：必須用 LangChain SystemMessage（而非 {"role": "system"} dict）。
    # LanguageAwareLLM._inject_language 偵測到 SystemMessage 才會「合併」
    # 語言指令到同一條 system（保留 JSON 指令）；否則走 else 插入獨立語言
    # system message——deepseek 的 json_object mode 檢查「system message 是否
    # 含 json 字樣」，獨立訊息會漏掉 → 400「Prompt must contain the word json」。
    from langchain_core.messages import SystemMessage

    sys_msg = SystemMessage(content=prompt)
    for attempt, kwargs in enumerate(
        ({"response_format": {"type": "json_object"}}, {}), start=1
    ):
        try:
            if hasattr(llm, "ainvoke"):
                resp = await llm.ainvoke([sys_msg], **kwargs)
            else:
                # 只提供同步 invoke 的相容 LLM：to_thread 避免阻塞 event loop。
                import asyncio

                resp = await asyncio.to_thread(llm.invoke, [sys_msg], **kwargs)
            text = resp.content if hasattr(resp, "content") else str(resp)
            parsed = _parse_clarify_options(text, language)
            if parsed:
                return parsed
        except Exception as e:  # noqa: BLE001 — 每種嘗試都要試過才 fallback
            logger.warning(
                "[Clarify] LLM option generation attempt %d failed for %r: %s",
                attempt,
                query[:20],
                str(e)[:300],
            )
            continue

    logger.warning(
        "[Clarify] LLM option generation failed for %r (fallback to hardcoded)",
        query[:20],
    )
    return None


def _parse_clarify_options(text: str, language: str) -> Optional[list[dict]]:
    """解析 LLM 回傳的選項 JSON，格式不合法回 None。

    容錯層層退化：
    1. 剝離 ```json markdown fence 後直接 json.loads
    2. 直接解析失敗 → 提取第一個「[」到最後一個「]」的子字串再解析
       （模型偶爾在 JSON 前後加說明文字）
    3. 載入結果若是 dict 且含 list 值（{"options": [...]} 等包裝）→ 用該 list
    4. 驗證：2-4 項、每項含非空 label + hint
    """
    import json as _json

    if not text:
        return None
    # 剝離可能的 markdown code fence
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    data = None
    try:
        data = _json.loads(text)
    except Exception:
        pass
    if data is None:
        # 說明文字包夾 JSON 陣列 → 提取陣列段再解析
        start, end = text.find("["), text.rfind("]")
        if 0 <= start < end:
            try:
                data = _json.loads(text[start : end + 1])
            except Exception:
                return None
    if isinstance(data, dict):
        # json_object mode 下模型可能回 {"options": [...]} / {"clarifications": [...]} 等
        # 包裝。先試常見 key，再退而找 dict 內第一個 2-4 元素的 list 值。
        for key in ("options", "choices", "clarifications", "items", "data", "result"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            for v in data.values():
                if isinstance(v, list):
                    data = v
                    break
            else:
                return None
    if not isinstance(data, list) or not (2 <= len(data) <= 4):
        return None
    options = []
    for item in data:
        if not isinstance(item, dict):
            return None
        label = str(item.get("label", "")).strip()
        hint = str(item.get("hint", "")).strip()
        if not label or not hint:
            return None
        options.append({"label": label[:30], "hint": hint[:60]})
    return options if len(options) >= 2 else None


# ============================================================================
# Wrong-Scope Clarify（Phase E）— 非空但答錯範圍的回應
#
# 動機（截圖鐵證）：使用者問「台股是否值得投資」（範圍/綜合問題），中等模型
# 直接答「台積電（2330）目前股價…」（特定股票）；使用者再說「我想要投資」
# （無標的意圖），模型被前文 context 帶偏，調加密貨幣工具。兩者都是「答非所問」。
#
# 與 Phase C/D 的差異：
# - Phase C（should_clarify）：response 非空且含「查無/不確定」→ 查無此標的
# - Phase D（should_clarify_vague_query）：response 空 → 模型放棄
# - Phase E（should_clarify_wrong_scope）：response 非空且**答對了某個標的**，
#   但那個標的**不是使用者問的範圍** → 偷換主題。本函式處理此情境。
# ============================================================================

# 市場命名空間詞（範圍問題訊號）——繁簡 + en + ru
_SCOPE_MARKET_TERMS = [
    # zh-TW / zh-CN
    "美股", "台股", "臺股", "a股", "陸股", "港股", "日股", "韓股", "印股",
    "英股", "歐股", "股市", "整體", "大盤", "大市", "指數", "指数",
    "市場", "市场", "板塊", "板块", "產業", "产业", "類股", "板块",
    # en
    "market", "index", "overall", "broad",
]

# 無標的意圖詞（使用者講了意圖但沒講標的）——範圍問題的另一種訊號
_INTENT_NO_TARGET_TERMS = [
    # zh-TW / zh-CN
    "是否值得", "值不值得", "適合投資", "適合買", "适合买", "該不該",
    "该不该", "進場", "进场", "出場", "出场", "要不要", "會不會",
    "会不会", "我想要投資", "我想要投资", "我想投資", "我想投资",
    "想投資", "想投资", "適合進場", "适合进场", "可以投資嗎", "可以投资吗",
    # en
    "worth investing", "worth it", "should i", "want to invest",
    "i want to invest", "good time to", "should i enter",
]

# 廣度詞彙——若 response 含這些，視為「正確範圍答案」（只是舉例個股），不觸發
_BREADTH_INDICATORS = [
    # zh-TW / zh-CN
    "整體", "大盤", "大市", "指數", "指数", "平均", "普遍", "整體市場",
    "整体市场", "全體", "宏观", "宏觀", "整體偏", "整体偏", "加權",
    "加权", "市值", "多數", "多数", "廣泛", "广泛", "板塊",
    # en
    "overall", "broadly", "market-wide", "market wide", "index",
    "average", "sector-wide", "as a whole", "broad market", "aggregate",
]

# 編譯一次
_SCOPE_MARKET_RE = re.compile(
    "|".join(re.escape(t) for t in _SCOPE_MARKET_TERMS), re.IGNORECASE
)
_INTENT_NO_TARGET_RE = re.compile(
    "|".join(re.escape(t) for t in _INTENT_NO_TARGET_TERMS), re.IGNORECASE
)
_BREADTH_RE = re.compile(
    "|".join(re.escape(t) for t in _BREADTH_INDICATORS), re.IGNORECASE
)

# Skill / memory 管理意圖——這類查詢不是投資問題，不該被 vague/scope clarify 攔截。
# 配對中英文：「skill / 技能 / 分析方法 / 記憶 / memory」+ 動詞（列出/建立/刪除/查看/有哪些）。
# 例：「我有哪些 skill」「列出所有分析方法」「幫我建立 skill」「刪除 test skill」。
_SKILL_MEMORY_INTENT_RE = re.compile(
    r"(skill|技能|分析方法|分析方式|記憶|memory|remember|propose_custom|"
    r"list_my_skills|個人方法|自訂方法|自定义方法)",
    re.IGNORECASE,
)

# 投資意圖——fallback clarify 選項只有投資意圖查詢才給投資選項（整體大盤/特定股票…），
# 非投資查詢給中性通用選項（重新描述/給標的/換問法），避免誤導。
_INVESTMENT_INTENT_RE = re.compile(
    r"(股票|股市|台股|臺股|美股|港股|日股|韓股|a股|陸股|加密|加密貨幣|幣|比特幣|以太坊|"
    r"ton|sol|eth|btc|外匯|匯率|期貨|大宗商品|黃金|白銀|原油|價格|行情|走勢|漲|跌|"
    r"買|賣|投資|理財|進場|出場|值得|技術面|基本面|分析|指數|大盤|portfolio|"
    r"stock|crypto|bitcoin|ethereum|forex|commodity|gold|silver|oil|price|"
    r"invest|trade|bull|bear|market|index)",
    re.IGNORECASE,
)

# TW 4-6 位數代號（2330, 2454 等）
_TW_NUMBER_RE = re.compile(r"(?<![\d.])(\d{4,6})(?!\d)")
# 拉丁大寫 ticker（2-6 字元 + 可選 1 數字）。
# 已知 crypto 的排除改用 _known_crypto_symbols()（從 company_aliases.json 派生）。
_LATIN_TICKER_RE = re.compile(r"\b[A-Z]{2,6}\d?\b")

# Crypto 意圖詞（Gap 1 子情境）：response 跳到泛 crypto 言論但沒有具體 ticker。
# 用來抓「使用者問『我想要投資』（無 crypto 意圖），模型被前文帶偏調 crypto」。
_CRYPTO_INTENT_TERMS = [
    # zh-TW / zh-CN
    "加密貨幣", "数字货币", "數字貨幣", "虚拟货币", "虛擬貨幣",
    "虚拟资产", "虛擬資產", "區塊鏈", "区块链", "代幣", "代币",
    "比特", "以太坊", "以太坊", "币圈", "幣圈", "加密資產", "加密资产",
    # en
    "cryptocurrency", "crypto ", " crypto", "bitcoin", "ethereum",
    "blockchain", "digital asset", "token", "altcoin", "defi",
]
_CRYPTO_INTENT_RE = re.compile(
    "|".join(re.escape(t) for t in _CRYPTO_INTENT_TERMS), re.IGNORECASE
)


def _extract_tickers_zh(text: str, include_crypto: bool = False) -> set:
    """從文字中抽取所有 ticker（拉丁 + TW 4位數 + 中文 alias 名）。

    補 `_detect_query_ticker` 的 gap：後者只 match 拉丁大寫，看不到「台積電」
    或「2330」。本函式結合三種策略：

    1. 拉丁大寫 ticker（2-6 char）
    2. TW 4-6 位數代號（2330、2454）
    3. 中文公司名/暱稱 — 透過 ``_lookup_local_alias`` 查 ``data/company_aliases.json``
       （curated + learned ≈ 250 個中文 alias，含台積電/鴻海/蘋果/輝達/比特幣等），
       純本地 JSON 查表、零 API call。**不含** preloader 預載的 ~11000 個 TW/US
       公司名（那些是給精確 resolve_symbol lookup 用，不參與子字串掃描）。

    Args:
        text: 要掃描的文字。
        include_crypto: 是否保留 crypto ticker（BTC/ETH 等已知加密貨幣）。
            - **query 側用 False**（預設）：query 裡的 BTC 是明確的，不需 clarify。
            - **response 側用 True**：response 裡出現 crypto 是「模型偷換標的」的證據
              （Gap 1 修復：使用者問「我想要投資」無標的，模型被前文 context 帶偏調
              crypto 工具——這時 response 裡的 BTC/比特幣 正是該被攔的訊號）。

    回傳 normalized ticker 字串的 set（如 {"2330", "TSMC", "AAPL"}）。
    中文 alias 會被 normalize 成 alias 表裡的 symbol（台積電→"2330"）。
    """
    found: set = set()
    if not text or not isinstance(text, str):
        return found

    # 1. 拉丁大寫 ticker
    known_crypto = _known_crypto_symbols()
    for m in _LATIN_TICKER_RE.findall(text):
        if include_crypto or m not in known_crypto:
            found.add(m)

    # 2. TW 4-6 位數代號
    for m in _TW_NUMBER_RE.findall(text):
        found.add(m)

    # 3. 中文 alias（透過本地映射表）— 只查表、不啟動 API
    try:
        from core.tools.multi_market_resolver import _lookup_local_alias

        # 逐字掃所有 alias key 是否以 substring 出現
        # （_lookup_local_alias 要求整段字串是 key，這裡要掃 substring）
        aliases = _load_alias_keys_cached()
        lower_text = text.lower()
        for key in aliases:
            if key and key in lower_text:
                entry = _lookup_local_alias(key)
                if entry and entry.symbol:
                    # include_crypto=False 時，排除 alias 解析出的 crypto symbol
                    # （比特幣→BTC 等，與 query 側排除一致）
                    if (
                        include_crypto
                        or entry.symbol not in known_crypto
                    ):
                        found.add(entry.symbol)
    except Exception as e:
        logger.debug(f"[Clarification] _extract_tickers_zh alias scan failed: {e}")

    return found


# 模組級 cache：alias keys 只載一次（curated + learned ≈ 250 個，載入 < 1ms）
_alias_keys_cache: Optional[set] = None


def _load_alias_keys_cached() -> set:
    """載入本地 alias 表的 key（中文暱稱 + 小寫 crypto 名），快取在模組級。

    只讀磁碟上的 curated + learned alias（company_aliases.json +
    learned_aliases.json），**不讀** ``_LOCAL_ALIASES`` global——因為啟動時
    preloader 會把 ~11000 個 TW/US 公司名 merge 進該 global。

    若 substring 掃描納入那 11000 個長公司名（如 "apple inc."），
    ``_extract_tickers_zh`` 的 O(n) 掃描會被放大約 40 倍，且每個 agent
    請求觸發多次。preloaded alias 本就是給精確 lookup 用（resolve_symbol），
    不該參與子字串掃描。
    """
    global _alias_keys_cache
    if _alias_keys_cache is not None:
        return _alias_keys_cache
    try:
        import json
        from pathlib import Path

        from core.tools.multi_market_resolver import _flatten_aliases

        base_path = Path(__file__).parent.parent.parent / "data"
        flat: dict = {}
        # 來源 1：curated 手動表
        try:
            curated = json.loads(
                (base_path / "company_aliases.json").read_text(encoding="utf-8")
            )
            flat.update(_flatten_aliases(curated))
        except Exception as e:
            logger.debug(f"[Clarification] curated aliases load failed: {e}")
        # 來源 2：動態學習（不含 preloader 預載的 11000 個）
        try:
            learned_path = base_path / "learned_aliases.json"
            if learned_path.exists():
                learned = json.loads(learned_path.read_text(encoding="utf-8"))
                flat.update(_flatten_aliases(learned))
        except Exception as e:
            logger.debug(f"[Clarification] learned aliases load failed: {e}")

        keys = {
            k.strip().lower()
            for k, v in flat.items()
            if k != "_meta" and isinstance(v, dict)
        }
        _alias_keys_cache = keys
        return keys
    except Exception as e:
        logger.debug(f"[Clarification] _load_alias_keys_cached failed: {e}")
        _alias_keys_cache = set()
        return _alias_keys_cache


# 模組級 cache：已知 crypto symbol 清單（從 company_aliases.json 派生，單一真相來源）。
# 取代原本寫死的 _KNOWN_CRYPTO_TICKERS(18) 和 _KNOWN_CRYPTO(9) 兩份不同步清單。
_known_crypto_symbols_cache: Optional[frozenset] = None


def _known_crypto_symbols() -> frozenset:
    """從 company_aliases.json 派生已知 crypto 清單（單一真相來源）。

    取代原本寫死且不同步的 _KNOWN_CRYPTO_TICKERS(18)/_KNOWN_CRYPTO(9)。
    JSON 新增幣種時自動同步，不再 drift。graceful：載入失敗回空集合。
    """
    global _known_crypto_symbols_cache
    if _known_crypto_symbols_cache is not None:
        return _known_crypto_symbols_cache
    try:
        from core.tools.multi_market_resolver import _load_local_aliases

        # company_aliases.json 是扁平結構：key=alias, value={symbol, market, name}
        # 過濾 market=="crypto" 的 entries，取 unique symbol。
        data = _load_local_aliases() or {}
        symbols = frozenset(
            v.get("symbol")
            for v in data.values()
            if isinstance(v, dict) and v.get("market") == "crypto" and v.get("symbol")
        )
        _known_crypto_symbols_cache = symbols
        return symbols
    except Exception as e:
        logger.debug(f"[Clarification] _known_crypto_symbols failed: {e}")
        _known_crypto_symbols_cache = frozenset()
        return _known_crypto_symbols_cache


# 「深度要求詞」——使用者要求更全面/深入分析，不是「標的不明」。
# 例：「整體評估」「全面分析」「綜合判斷」「詳細分析」「深入探討」
_DEPTH_REQUEST_TERMS = [
    "整體評估", "全面評估", "綜合評估", "整體分析", "全面分析",
    "綜合分析", "綜合判斷", "整體判斷", "詳細分析", "深入分析",
    "深入探討", "全面評價", "整體評價", "綜合評價", "overall assessment",
    "comprehensive analysis", "in-depth analysis",
]
_DEPTH_REQUEST_RE = re.compile(
    "|".join(re.escape(t) for t in _DEPTH_REQUEST_TERMS), re.IGNORECASE
)

# 代詞指代——query 用「他/它/這個/該/這支」等指代前文標的，代表標的明確（來自 context）。
_PRONOUN_REFERENCE_TERMS = [
    "他", "她", "它", "這個", "这个", "這支", "这支", "該", "该",
    "這檔", "这档", "這個幣", "这个币", "這檔股票", "这档股票",
    "這標的", "这标的", "前面", "剛剛", "刚刚", "剛說", "刚说",
]
_PRONOUN_REFERENCE_RE = re.compile(
    "|".join(re.escape(t) for t in _PRONOUN_REFERENCE_TERMS), re.IGNORECASE
)


def _query_is_scope_question(query: str) -> bool:
    """判斷 query 是否為「範圍/綜合問題」（標的本身未確定）。

    條件（OR）：含市場命名空間詞（美股/台股/整體/大盤…）OR 含無標的意圖詞
    （是否值得/值不值得/我想要投資…）。且 query 本身**沒有具體 ticker**。
    """
    if not query or len(query.strip()) < 3:
        return False
    # 「整體評估/全面分析/綜合判斷」是要求深度，不是「標的不明」。
    # 這類詞配代詞指代（他/它/這個/該）時，標的來自前文明確，不該釐清。
    # 例：「整體評估的話你認為他現在是否值得購買」→ 他=前文標的，不該釐清。
    if _DEPTH_REQUEST_RE.search(query) and _PRONOUN_REFERENCE_RE.search(query):
        return False
    has_scope_term = bool(_SCOPE_MARKET_RE.search(query)) or bool(
        _INTENT_NO_TARGET_RE.search(query)
    )
    if not has_scope_term:
        return False
    # query 有具體 ticker → 不是範圍問題（使用者已指名特定標的）。
    # 注意：query 側偵測要用 include_crypto=True——query 裡的 BTC/TON/ETH 是
    # 明確標的（使用者指名了），不該因為「crypto 被 query 側排除」而誤判為範圍問題。
    # （response 側的 include_crypto 是另一個語意：response 裡的 crypto 是污染訊號。）
    query_tickers = _extract_tickers_zh(query, include_crypto=True)
    return len(query_tickers) == 0


async def should_clarify_wrong_scope(
    query: str,
    response: str,
    used_tools: Optional[list] = None,
    already_clarified: bool = False,
    language: str = "zh-TW",
    llm=None,
) -> Optional[dict]:
    """偵測「模型答錯範圍」的回應（非空但答非所問），回傳 clarify payload。

    與 Phase C/D 互補：
    - Phase C：response 非空 + 含「查無」→ 查無此標的
    - Phase D：response 空 → 模型放棄
    - **Phase E（本函式）**：response 非空 + 答了某標的，但**不是使用者問的範圍**
      → 偷換主題（如「台股」答成「台積電」、「我想投資」答成加密貨幣）

    Args:
        query: 使用者原始問題。
        response: LLM 最終回應（非空；空回應歸 Phase D）。
        used_tools: 本次執行呼叫的工具（目前未嚴格用，保留擴充；主要靠 query/response 比對）。
        already_clarified: 該 session 是否已 clarify 過（防無限追問）。
        language: 語言。

    Returns:
        dict {type: "clarify", question, options, select_mode} 或 None。

    觸發條件（全部滿足，保守設計防誤觸發）：
    1. 已 clarify 過 → 不再觸發（防無限迴圈）
    2. response 非空（空回應歸 Phase D）
    3. query 是範圍問題（含市場/無標的意圖詞 + 無具體 ticker）
    4. response 出現 query 沒提的具體 ticker
       **AND** response 缺乏廣度詞彙（整體/大盤/指數…）
       → 防誤觸發：response 若含廣度詞，視為正確範圍答案（只是舉例個股），不觸發
    """
    if already_clarified:
        return None
    # Skill / memory 管理意圖不是投資範圍問題，不該走 wrong_scope clarify。
    if _SKILL_MEMORY_INTENT_RE.search(query):
        return None
    if not response or not response.strip():
        return None  # 空回應歸 Phase D
    if not query or len(query.strip()) < 3:
        return None

    # 條件 3：query 必須是範圍問題
    if not _query_is_scope_question(query):
        return None

    # 條件 4a：response 出現 query 沒提的具體 ticker
    # Gap 1 修復（審計確認）：response 側用 include_crypto=True。
    # query 裡的 BTC 是明確的（不需 clarify）；但 response 裡的 BTC/比特幣 是
    # 「模型被前文 context 帶偏，偷換標的」的證據——使用者問「我想要投資」無標的，
    # 模型調 crypto 工具，這時 response 裡的 crypto 正是該攔的訊號。
    query_tickers = _extract_tickers_zh(query)  # query 側：排除 crypto（明確）
    response_tickers = _extract_tickers_zh(response, include_crypto=True)
    new_tickers = response_tickers - query_tickers

    # Gap 1 子情境：response 是泛 crypto 言論但沒有具體幣種 ticker
    # （如「加密貨幣整體來說是不錯的投資選擇…」）→ 抓不到 ticker，但仍是偷換標的。
    # 若 query 不含 crypto 意圖詞，response 卻跳到 crypto → 視同答錯範圍。
    crypto_context_contamination = False
    if not _CRYPTO_INTENT_RE.search(query) and _CRYPTO_INTENT_RE.search(response):
        crypto_context_contamination = True
        if not new_tickers:
            new_tickers = {"<crypto-context>"}  # 占位符，表示偵測到 crypto 污染
            logger.info(
                "[Clarification] wrong-scope: query=%r got generic crypto response "
                "(no specific ticker, but crypto intent in response without in query)",
                query[:40],
            )

    if not new_tickers:
        return None  # response 沒提新 ticker → 不是偷換主題

    # 條件 4b：response 必須缺乏廣度詞彙（防誤觸發）
    # 若 response 含「整體/大盤/指數/平均…」等，視為正確範圍答案（只是舉例），不觸發。
    # 但 Gap 1 例外：若 response 的「廣度」是 crypto 廣度（整體加密貨幣…）且 query
    # 不含 crypto 意圖，那不是「正確範圍」而是「crypto 污染」→ 不豁免，仍觸發。
    if _BREADTH_RE.search(response) and not crypto_context_contamination:
        return None

    # 全部條件滿足 → 組 clarify payload（複用 vague-query 的 4 選項格式，前端零改動）
    logger.info(
        "[Clarification] wrong-scope detected: query=%r answered about tickers=%s "
        "(query scope terms without these tickers)",
        query[:40],
        sorted(new_tickers),
    )
    question, options = await _build_vague_query_clarification(query, language, llm=llm)
    payload: dict = {"type": "clarify", "question": question}
    if options:
        payload["options"] = options
        payload["select_mode"] = "single"
    return payload


def should_clarify(
    response: str,
    used_tools: list,
    query: str,
    already_clarified: bool = False,
) -> Optional[str]:
    """判斷是否該觸發 progressive clarification。

    Args:
        response: LLM 的最終回應。
        used_tools: 本次執行實際呼叫的工具清單。
        query: 使用者的原始問題。
        already_clarified: 該 session 是否已觸發過 clarification（避免無限追問）。

    Returns:
        clarification question 字串，或 None（不需 clarify）。

    觸發條件（OR，任一滿足即可，但都要 used_tools=[] 且 not already_clarified）：

    **路徑 1（既有）：回應含「不確定 / 查無 / 找不到」**
    - LLM 自己承認找不到（「查無 SNXX 此幣」）

    **路徑 2（2026-07-20 新增）：回應含「正在獲取」「正在計算」幻覺動作詞**
    - LLM 沒用工具卻編造「正在獲取即時價格...」「RSI 分析...」
    - AKE 案例就是這條路徑：used_tools=[] + 回應含「正在獲取即時價格」
    - 抓到後改走 ``resolve_symbol_all_markets`` 列出真實候選

    兩條路徑都要求：
    1. 該 session 還沒 clarify 過
    2. LLM 沒用任何工具
    3. query 中有未知代號（不是 BTC/ETH 等已知加密貨幣）
    """
    if already_clarified:
        return None

    # 必須沒用工具（用了工具還找不到才算「真的查無」；用了工具還生幻覺就是另一個 bug）
    if used_tools:
        return None

    if not response or not isinstance(response, str):
        return None

    # query 中必須有未知代號
    ticker = _detect_query_ticker(query)
    if ticker is None:
        return None

    # 路徑 1：明確的「查無 / 不確定」
    if _UNCERTAINTY_RE.search(response):
        return _build_basic_clarification(ticker)

    # 路徑 2：幻覺動作詞（沒用工具卻說「正在獲取...」）
    if _FAKE_ACTION_RE.search(response):
        logger.warning(
            "[Clarification] hallucination detected for ticker=%r "
            "(used_tools=[], response contains fake action phrase)",
            ticker,
        )
        # 觸發多市場候選列舉（由 claw_loop 接手跑 resolve_symbol_all_markets）
        return _MULTI_MARKET_TRIGGER_SENTINEL

    return None


# ============================================================================
# Clarification 訊息建構
# ============================================================================

#: should_clarify 的特殊回傳值：指示 caller「該跑 resolve_symbol_all_markets」。
#: 不是 None（要觸發 clarification），但也不是最終訊息（要再 enrich）。
#: caller（claw_loop）拿到這個 sentinel 就會跑 multi-market 查詢並組最終訊息。
_MULTI_MARKET_TRIGGER_SENTINEL = "__MULTI_MARKET_LOOKUP_NEEDED__"


def is_multi_market_trigger(value: object) -> bool:
    """判斷 should_clarify 的回傳值是否為「該跑 multi-market lookup」sentinel。"""
    return value == _MULTI_MARKET_TRIGGER_SENTINEL


def _build_basic_clarification(ticker: str) -> str:
    """既有 4 選項 clarification（用於「查無 / 不確定」路徑）。"""
    return (
        f"您查詢的「{ticker}」我目前無法確認是哪類資產。"
        "請問它是：\n"
        "1. 加密貨幣（Cryptocurrency）\n"
        "2. 美股（US Stock / ETF）\n"
        "3. 台股（TW Stock）\n"
        "4. 其他市場（港股/日股/外匯/大宗商品等）\n"
        "請回覆數字或說明，我會用正確的工具為您查詢。"
    )


def build_multi_market_clarification(
    ticker: str, candidates_json: str, language: str = "zh-TW"
) -> str:
    """把 resolve_symbol_all_markets 結果組成給使用者的 clarification 訊息。

    Args:
        ticker: 使用者問的 ticker（如 "AKE"）。
        candidates_json: resolve_symbol_all_markets_sync 回傳的 JSON 字串。
        language: 使用者語言（zh-TW / zh-CN / en / ru）。

    Returns:
        列出所有候選的 clarification 訊息，含支援 / 不支援標示。
    """
    import json as _json

    try:
        data = _json.loads(candidates_json) if isinstance(candidates_json, str) else candidates_json
    except (ValueError, TypeError):
        data = {}

    candidates = data.get("candidates", []) if isinstance(data, dict) else []
    if not candidates:
        # 沒候選 → 退回基本 clarification
        return _build_basic_clarification(ticker)

    # 分類候選
    supported: list = []
    unsupported: list = []
    for c in candidates:
        if c.get("supported", True):
            supported.append(c)
        else:
            unsupported.append(c)

    # 組訊息（依語言）
    if language == "en":
        lines = [f'"{ticker}" could refer to multiple assets. I found these candidates:']
        lines.append("")
        for i, c in enumerate(supported, 1):
            name = c.get("name") or c.get("symbol") or ticker
            market = c.get("market", "?")
            verified = "verified" if c.get("verified") else "unverified"
            source = c.get("source", "")
            extra = c.get("extra", {})
            mcap_rank = extra.get("mcap_rank")
            mcap_str = f" · market cap rank #{mcap_rank}" if mcap_rank else ""
            lines.append(
                f"{i}. ✅ **{name}** ({market}) — source: {source} ({verified}){mcap_str}"
            )
        for i, c in enumerate(unsupported, len(supported) + 1):
            market = c.get("market", "?")
            note = c.get("note", "this platform does not support this market")
            lines.append(f"{i}. ❌ _({market})_ — {note}")
        lines.append("")
        lines.append(
            'Reply with a number (e.g. "1") to analyze that one, '
            'or "all" to query all supported candidates.'
        )
        return "\n".join(lines)

    if language == "ru":
        lines = [f'«{ticker}» может относиться к нескольким активам. Найдены кандидаты:']
        lines.append("")
        for i, c in enumerate(supported, 1):
            name = c.get("name") or c.get("symbol") or ticker
            market = c.get("market", "?")
            verified = "подтверждено" if c.get("verified") else "не подтверждено"
            source = c.get("source", "")
            lines.append(f"{i}. ✅ **{name}** ({market}) — источник: {source} ({verified})")
        for i, c in enumerate(unsupported, len(supported) + 1):
            market = c.get("market", "?")
            note = c.get("note", "платформа не поддерживает этот рынок")
            lines.append(f"{i}. ❌ _({market})_ — {note}")
        lines.append("")
        lines.append(
            'Ответьте номером (например «1»), чтобы проанализировать выбранный, '
            'или «все», чтобы запросить все поддерживаемые.'
        )
        return "\n".join(lines)

    # zh-TW / zh-CN（共用繁簡，差異小）
    lines = [f"您問的「{ticker}」可能是以下其中之一，我查到這些候選："]
    lines.append("")
    for i, c in enumerate(supported, 1):
        name = c.get("name") or c.get("symbol") or ticker
        market = c.get("market", "?")
        verified = "已驗證" if c.get("verified") else "未驗證"
        source = c.get("source", "")
        extra = c.get("extra", {})
        mcap_rank = extra.get("mcap_rank")
        mcap_str = f" · 市值排名 #{mcap_rank}" if mcap_rank else ""
        market_zh = _MARKET_LABEL_ZH.get(market, market)
        lines.append(
            f"{i}. ✅ **{name}**（{market_zh}）— 來源：{source}（{verified}）{mcap_str}"
        )
    for i, c in enumerate(unsupported, len(supported) + 1):
        market = c.get("market", "?")
        market_zh = _MARKET_LABEL_ZH.get(market, market)
        note = c.get("note", "本平台目前不支援此市場")
        lines.append(f"{i}. ❌ _（{market_zh}）_ — {note}")
    lines.append("")
    lines.append("請回覆想看哪個（例如「1」或名稱），或回「全部」我會一次查所有支援的選項。")
    return "\n".join(lines)


# 市場代碼 → 中文標籤
_MARKET_LABEL_ZH = {
    "crypto": "加密貨幣",
    "us": "美股",
    "tw": "台股",
    "hk": "港股",
    "jp": "日股",
    "kr": "韓股",
    "in": "印股",
    "cn": "陸股",
    "fr": "法股",
    "de": "德股",
    "au": "澳股",
    "uk": "英股",
}


__all__ = [
    "should_clarify",
    "should_clarify_vague_query",
    "should_clarify_wrong_scope",
    "is_multi_market_trigger",
    "build_multi_market_clarification",
    "_detect_query_ticker",
    "_extract_tickers_zh",
    "_query_is_scope_question",
    "_FAKE_ACTION_RE",
    "_UNCERTAINTY_RE",
]
