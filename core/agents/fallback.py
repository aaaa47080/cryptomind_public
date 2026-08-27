"""
BYOK Fallback Provider Chain — 骨架（預設停用）。

背景
----
Hermes-Agent 在 LLM 持續空回時會切到 fallback provider/model。CryptoMind 是
BYOK 多 provider 架構，理論上很適合加這層：當使用者的 BYOK 模型爛到不行
（例如免費額度的開源模型持續回空），自動 fallback 到 server-side 預設模型
完成這次請求。

但這涉及 **server-side 成本**（fallback 用 server key，等於免費借用資源），
屬於產品決策。本模組只實作骨架，預設停用。未來 DANNY 確認成本/體驗 trade-off
後，只需設定 ``BYOK_FALLBACK_ENABLED=true`` + ``BYOK_FALLBACK_PROVIDER`` +
``BYOK_FALLBACK_MODEL`` + ``BYOK_FALLBACK_API_KEY`` 即可啟用。

設計
----
- ``should_fallback(result, retry_counter)``：判斷要不要 fallback
- ``get_fallback_client()``：從 env 組 fallback client（None = 未啟用）
- 整合點：``claw_loop._claw_loop_node`` 在 ``execute_streaming`` 失敗後檢查

未啟用時，所有函式 no-op，不影響任何現有流程。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Cascade-loop 防護（學 Hermes fallback-providers doc + issue #24996）────────
# Hermes 早期沒有「每輪最多一次」限制時，多 provider 同時非重試失敗會
# tight-loop 重 marshalling 80k token context 燒爆記憶體。
#
# 設計（turn-scoped + at most once per turn）：
# - 每個「turn」（一個使用者訊息 = 一次 claw_loop 執行）最多 fallback 1 次。
# - 跨 turn 的短時間內（CASCADE_WINDOW_SECONDS）累計超 MAX_CASCADE_FALLBACKS
#   → 暫時熔斷（認定 fallback provider 本身有問題，不再燒錢）。
MAX_FALLBACKS_PER_TURN = 1
MAX_CASCADE_FALLBACKS = 3  # 窗口內累計上限
CASCADE_WINDOW_SECONDS = 60  # 熔斷窗口

# 模組級計數器。claw_loop 每個請求開始時呼叫 reset_turn_fallback_guard()。
_turn_fallback_count = 0
_cascade_timestamps: list[float] = []


def reset_turn_fallback_guard() -> None:
    """每個使用者訊息（turn）開始時重設 per-turn 計數器。

    claw_loop._claw_loop_node 開頭呼叫。對齊 Hermes「每個新 user message 都從
    主模型重來，fallback 每輪重置」。
    """
    global _turn_fallback_count
    _turn_fallback_count = 0


def _cascade_tripped() -> bool:
    """窗口內 fallback 累計是否超上限（熔斷）。"""
    now = time.monotonic()
    # 清掉過期時間戳
    cutoff = now - CASCADE_WINDOW_SECONDS
    global _cascade_timestamps
    _cascade_timestamps = [ts for ts in _cascade_timestamps if ts > cutoff]
    return len(_cascade_timestamps) >= MAX_CASCADE_FALLBACKS


def _record_fallback() -> None:
    """記錄一次 fallback（供 cascade 計數）。"""
    global _turn_fallback_count, _cascade_timestamps
    _turn_fallback_count += 1
    _cascade_timestamps.append(time.monotonic())


def is_fallback_enabled() -> bool:
    """Fallback 是否啟用。

    啟用條件（全部滿足）：
    1. ``BYOK_FALLBACK_ENABLED=true``
    2. ``BYOK_FALLBACK_PROVIDER`` 有設
    3. ``BYOK_FALLBACK_API_KEY`` 有設（或對應 provider 的 env key 有設）
    4. 非 TEST_MODE（避免測試意外打到 fallback）
    """
    if os.getenv("TEST_MODE", "false").lower() in {"true", "1", "yes"}:
        return False
    if os.getenv("BYOK_FALLBACK_ENABLED", "false").lower() not in {"true", "1", "yes"}:
        return False
    if not os.getenv("BYOK_FALLBACK_PROVIDER"):
        return False
    if not os.getenv("BYOK_FALLBACK_API_KEY"):
        return False
    return True


def should_fallback(
    final_response: Optional[str],
    used_tools: list,
    retry_exhausted: bool,
    error: Optional[BaseException] = None,
) -> bool:
    """判斷是否該走 fallback。

    觸發條件（AND）：
    1. ``is_fallback_enabled()`` 為 True
    2. ``retry_exhausted`` 為 True（recovery 都試過了）
       **或** error 是 capacity error（402/quota —— 主模型配額耗盡，retry 無
       意義，該換 provider，學 Hermes fallback-providers doc）
    3. ``final_response`` 是空 or 是 fallback 訊息（例如「模型沒有產生回應」）
    4. 本 turn 還沒 fallback 過（turn-scoped at most once，防 cascade loop）
    5. 熔斷未觸發（窗口內累計未超 MAX_CASCADE_FALLBACKS）

    Args:
        final_response: claw_loop 的最終回應。
        used_tools: 本次用過的工具（資訊用，目前不影響判斷）。
        retry_exhausted: RetryCounter 是否已耗盡。
        error: 觸發失敗的例外（若有）。capacity error 直接觸發 fallback。

    Returns:
        True 若該 fallback。
    """
    if not is_fallback_enabled():
        return False
    # turn-scoped：每輪最多一次
    if _turn_fallback_count >= MAX_FALLBACKS_PER_TURN:
        return False
    # cascade 熔斷
    if _cascade_tripped():
        logger.warning(
            "[Fallback] cascade 熔斷：%ds 內已 fallback %d 次，暫停 fallback",
            CASCADE_WINDOW_SECONDS,
            MAX_CASCADE_FALLBACKS,
        )
        return False
    # 觸發條件：retry 耗盡 OR capacity error（402/quota 該換 provider）
    from .rate_limit import is_capacity_error

    capacity_triggered = error is not None and is_capacity_error(error)
    if not retry_exhausted and not capacity_triggered:
        return False
    if final_response and len(final_response) > 50:
        # 有實質內容（>50 字）就不 fallback
        return False
    return True


def mark_fallback_used() -> None:
    """fallback 執行後呼叫，記錄計數（供 turn-scoped + cascade）。

    claw_loop 在實際跑完 fallback client 後呼叫。
    """
    _record_fallback()


def get_fallback_client() -> Optional[Any]:
    """從 env 組 fallback LLM client。

    Fallback 用較小的 max_tokens（CHAT_MAX_OUTPUT_TOKENS_FALLBACK=6144），
    保留預扣緩衝避免 402；fallback 模型通常用 server-side 較強模型，不需要 8K。

    Returns:
        LangChain LLM client，或 None（未啟用 / 設定不完整）。
    """
    if not is_fallback_enabled():
        return None
    try:
        from utils.user_client_factory import (
            CHAT_MAX_OUTPUT_TOKENS_FALLBACK,
            create_user_llm_client,
        )

        provider = os.getenv("BYOK_FALLBACK_PROVIDER", "")
        api_key = os.getenv("BYOK_FALLBACK_API_KEY", "")
        model = os.getenv("BYOK_FALLBACK_MODEL")
        return create_user_llm_client(
            provider=provider,
            api_key=api_key,
            model=model,
            max_tokens=CHAT_MAX_OUTPUT_TOKENS_FALLBACK,
        )
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to build fallback client: %s", exc)
        return None


# Fallback provider 呼叫的硬上限（秒）。
# Hermes #12770 教訓：cascade fallback 易浪費 20-60s。加 30s 上限，
# 超過就直接放棄 fallback，走既有的 _no_valid_result_message。
FALLBACK_TIMEOUT_SECONDS = 30


__all__ = [
    "is_fallback_enabled",
    "should_fallback",
    "get_fallback_client",
    "reset_turn_fallback_guard",
    "mark_fallback_used",
    "FALLBACK_TIMEOUT_SECONDS",
    "MAX_FALLBACKS_PER_TURN",
    "MAX_CASCADE_FALLBACKS",
    "CASCADE_WINDOW_SECONDS",
]
