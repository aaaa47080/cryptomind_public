"""Telegram Bot chat handler — core logic invoked by /api/telegram/chat.

This mirrors ``api/routers/analysis.py`` but without SSE streaming: the
bot receives the final response text and delivers it to the Telegram
user as one (or a few split) messages.

The flow:
1. Resolve ``telegram_id`` -> ``user_id`` via ``telegram_bindings``.
2. Load the user's BYOK LLM credentials (``user_api_keys``).
3. Bootstrap a ManagerAgent (LangGraph) for this user/session.
4. Invoke the graph synchronously and capture the final response.
5. Persist the user message + assistant reply to conversation_history.
6. Return the text to the bot.

Sessions: each Telegram binding gets a single rolling session id of the
form ``tg:{telegram_id}``. This keeps bot chats separate from web chats
while still using the same conversation_history table.
"""

from __future__ import annotations

import asyncio
import hashlib

from fastapi import HTTPException

from api.routers.telegram_link import ChatResponse
from api.user_llm import resolve_user_llm_credentials
from api.utils import logger, run_sync
from core.agents.bootstrap import bootstrap
from core.agents.manager import MANAGER_GRAPH_RECURSION_LIMIT
from core.database import (
    create_session,
    get_binding_by_telegram_id,
    get_chat_history,
    get_telegram_active_session,
    save_chat_message,
    set_current_session,
    update_telegram_last_used,
)
from utils.user_client_factory import create_user_llm_client

TG_SESSION_PREFIX = "tg"
MAX_RESPONSE_CHARS = 3500  # leave headroom under Telegram's 4096 limit
HISTORY_LIMIT = 20  # most recent N messages, mirrors web chat


def _tg_session_id(telegram_id: int) -> str:
    return f"{TG_SESSION_PREFIX}:{telegram_id}"


def _build_history_text(session_id: str, current_message: str) -> str:
    """撈回此 session 最近的對話並組成 history 字串，與 Web 端 (analysis.py)
    行為一致：依 token 預算截斷，確保 Telegram 也有上下文記憶。"""
    import math

    from core.agents.context_budget import CONTEXT_CHAR_BUDGET

    def estimate_tokens(text: str) -> int:
        return math.ceil(len(text) / 4)

    try:
        db_history = get_chat_history(session_id=session_id, limit=HISTORY_LIMIT)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Telegram chat: load history failed for session_id=%s: %s",
            session_id,
            exc,
            exc_info=True,
        )
        return ""

    all_lines: list[str] = []
    for msg in db_history:
        role = "助手" if msg.get("role") == "assistant" else "用戶"
        content = (msg.get("content") or "").strip()
        if content and content != current_message:
            all_lines.append(f"{role}: {content}")

    if not all_lines:
        return ""

    full_history_text = "\n".join(all_lines)
    history_budget = CONTEXT_CHAR_BUDGET // 3

    if estimate_tokens(full_history_text) <= history_budget // 4:
        return full_history_text

    # 超出預算：從最新往回保留，至少保留最後 4 行完整交談。
    selected: list[str] = []
    accumulated = 0
    for line in reversed(all_lines):
        line_tokens = estimate_tokens(line)
        if accumulated + line_tokens > history_budget and len(selected) >= 4:
            break
        selected.append(line)
        accumulated += line_tokens
    return "\n".join(reversed(selected))


async def run_telegram_chat(
    telegram_id: int,
    message: str,
    language: str = "zh-TW",
) -> ChatResponse:
    binding = await run_sync(get_binding_by_telegram_id, telegram_id)
    if not binding:
        raise HTTPException(
            status_code=403,
            detail="Telegram account is not linked. Please /link first.",
        )
    user_id = binding["user_id"]

    fake_user = {"user_id": user_id, "membership_tier": "free", "username": ""}
    credentials = await resolve_user_llm_credentials(fake_user, None)
    if not credentials:
        raise HTTPException(
            status_code=400,
            detail="NO_API_KEY",
        )

    try:
        # 使用用戶在 Web 端儲存的模型（resolve_user_llm_credentials 已回傳）。
        # 若未帶 model，create_user_llm_client 會 fallback 到 provider 預設模型，
        # 而 OpenRouter 預設模型未指定 max_tokens 時會以模型上限(如 65536)預扣額度，
        # 餘額不足即回 402。帶上用戶模型即與 Web 端行為一致。
        user_client = create_user_llm_client(
            provider=credentials["provider"],
            api_key=credentials["api_key"],
            model=credentials.get("model"),
        )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.error("create_user_llm_client failed: %s", exc)
        raise HTTPException(status_code=400, detail="INVALID_API_KEY") from exc

    # Telegram uses its own session namespace; do NOT consult web current_session
    # because that causes cross-platform context bleed (see memory bug 2026-06).
    session_id = await run_sync(
        get_telegram_active_session, telegram_id
    ) or _tg_session_id(telegram_id)

    # 只有預設 tg session 需要由 bot 端建立；切換到的 Web session 已存在，
    # 不要覆蓋它的標題。
    if session_id == _tg_session_id(telegram_id):
        await run_sync(create_session, session_id, "Telegram Chat", user_id)
    # 先撈歷史（此時當前訊息尚未寫入，不會被自己污染），再存當前訊息。
    history_text = await run_sync(_build_history_text, session_id, message)
    await run_sync(save_chat_message, "user", message, session_id, user_id)

    # bootstrap() 是同步函式，在 async 內直接呼叫會阻塞 loop 且 MCP loader 的
    # asyncio.run() 會失敗。走 run_sync bridge（對齊 analysis.py 的處理）。
    def _do_bootstrap():
        return bootstrap(
            llm_client=user_client,
            web_mode=False,
            language=language,
            user_tier="free",
            user_id=user_id,
            session_id=session_id,
            key_fingerprint=hashlib.sha256(
                credentials["api_key"].encode()
            ).hexdigest()[:8],
        )

    manager = await run_sync(_do_bootstrap)

    from langgraph.types import Command  # local import, heavy

    graph_input = Command(
        goto="claw_loop",
        update={
            "session_id": session_id,
            "query": message,
            "language": language,
            "history": history_text,
        },
    )
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": MANAGER_GRAPH_RECURSION_LIMIT,
    }

    try:
        result = await manager.graph.ainvoke(graph_input, config=config)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("graph.ainvoke failed: %s", exc)
        raise HTTPException(status_code=500, detail="ANALYSIS_FAILED") from exc

    final_response = result.get("final_response") or ""
    if not final_response:
        logger.warning(
            "Telegram chat: empty final_response, result keys=%s", list(result.keys())
        )
        final_response = "（無法產生回覆，請稍後再試。）"

    await run_sync(save_chat_message, "assistant", final_response, session_id, user_id)
    await run_sync(update_telegram_last_used, telegram_id)
    # 更新跨平台共用的當前對話 → 之後在網頁打開會接續這個 Telegram 對話。
    await run_sync(set_current_session, user_id, session_id)

    if len(final_response) > MAX_RESPONSE_CHARS:
        final_response = (
            final_response[:MAX_RESPONSE_CHARS]
            + "\n\n…（已截斷，完整內容請至 Web 版查看）"
        )

    return ChatResponse(
        success=True,
        response=final_response,
        session_id=session_id,
    )
