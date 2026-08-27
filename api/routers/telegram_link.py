"""Telegram Bot binding & chat endpoints.

Flow:
1. Web user authenticates normally (JWT), calls ``POST /api/telegram/link-token``
   to get a short-lived HMAC-signed token (5 min TTL).
2. User sends ``/link <token>`` to the bot in Telegram.
3. Bot calls ``POST /api/telegram/verify-link`` with the token + Telegram
   user info. Server verifies the token, creates a ``telegram_bindings``
   row, and returns success.
4. Subsequent bot messages hit ``POST /api/telegram/chat`` which resolves
   the binding, loads the user's BYOK api key, and runs the ManagerAgent
   graph directly (no SSE — returns the final text).

Auth model:
- ``link-token`` and ``status`` and ``unlink`` require a valid platform
  JWT (web user).
- ``verify-link`` and ``chat`` are internal bot endpoints authenticated
  with ``X-Bot-Secret`` (a shared secret from env ``BOT_INTERNAL_SECRET``).
  They never accept a user JWT — the bot proves who the user is by
  presenting a valid link token / binding row.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import SECRET_KEY, get_current_user
from api.middleware.rate_limit import limiter
from api.utils import logger, run_sync
from core.database import (
    check_session_ownership,
    create_telegram_binding,
    delete_binding_by_user_id,
    get_binding_by_telegram_id,
    get_binding_by_user_id,
    get_cache,
    get_current_session,
    get_sessions,
    get_telegram_active_session,
    get_user_by_id,
    set_cache,
    set_current_session,
    set_telegram_active_session,
)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

LINK_TOKEN_TTL_SECONDS = 5 * 60  # 5 minutes
_BOT_INTERNAL_SECRET = os.getenv("BOT_INTERNAL_SECRET", "")

if not _BOT_INTERNAL_SECRET and os.getenv("ENVIRONMENT", "").lower() in (
    "production",
    "prod",
):
    logger.warning(
        "BOT_INTERNAL_SECRET is empty in production — Telegram bot endpoints "
        "will reject all requests. Set BOT_INTERNAL_SECRET in the environment."
    )


# ============================================================================
# Internal auth dependency
# ============================================================================


def _require_bot_secret(x_bot_secret: Optional[str] = Header(default=None)) -> None:
    """Authenticate internal bot-to-API calls.

    The bot service shares a secret with the API via the
    ``BOT_INTERNAL_SECRET`` env var. In production this MUST be set; in
    development an empty secret is tolerated so local testing is easy.
    """
    expected = _BOT_INTERNAL_SECRET
    if not expected:
        if os.getenv("ENVIRONMENT", "").lower() in ("production", "prod"):
            raise HTTPException(status_code=503, detail="Bot service not configured")
        return  # dev mode: allow empty secret
    if not x_bot_secret or not hmac.compare_digest(x_bot_secret, expected):
        raise HTTPException(status_code=401, detail="Invalid bot secret")


# ============================================================================
# Link token generation / verification (HMAC-signed, stateless)
# ============================================================================


def _get_jwt_secret() -> str:
    """Get JWT secret from env, allowing test-time override via JWT_SECRET_KEY."""
    return os.environ.get("JWT_SECRET_KEY", SECRET_KEY)


def generate_link_token(user_id: str) -> str:
    """Issue a stateless, HMAC-signed link token.

    Format: ``{b64uid}.{exp_ts}.{nonce}.{hmac_hex}``
    ``b64uid`` is a base64url encoding of the user_id so the verifying
    side can recover the target user without a brute-force scan. The
    HMAC covers ``b64uid.exp_ts.nonce`` so the token cannot be
    re-targeted, extended, or replayed after expiry.
    """
    import base64

    b64uid = base64.urlsafe_b64encode(user_id.encode()).decode().rstrip("=")
    exp_ts = int(time.time()) + LINK_TOKEN_TTL_SECONDS
    nonce = secrets.token_hex(8)
    payload = f"{b64uid}.{exp_ts}.{nonce}"
    sig = hmac.new(
        _get_jwt_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{sig}"


def verify_link_token(token: str) -> Optional[tuple[str, int]]:
    """Verify a link token and recover the (user_id, exp_ts) it carries.

    Returns ``(user_id, exp_ts)`` if the token is valid and not expired,
    otherwise ``None``.
    """
    import base64

    try:
        b64uid, exp_ts_str, nonce, sig = token.split(".", 3)
    except ValueError:
        return None

    try:
        exp_ts = int(exp_ts_str)
    except ValueError:
        return None
    if exp_ts < int(time.time()):
        return None

    payload = f"{b64uid}.{exp_ts_str}.{nonce}"
    expected_sig = hmac.new(
        _get_jwt_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None

    # Decode user_id (add back padding stripped during encoding).
    padding = "=" * (-len(b64uid) % 4)
    try:
        user_id = base64.urlsafe_b64decode(b64uid + padding).decode()
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return None
    return user_id, exp_ts


# ============================================================================
# One-time link token enforcement
# ============================================================================
#
# The link token is a stateless HMAC bearer credential with a 5-min TTL. To
# stop a leaked token being replayed within that window (an attacker binding
# their own Telegram to the victim's account), we mark each token's nonce as
# consumed after a successful bind and reject any re-use. Backed by the shared
# cache (Redis → DB fallback). Fail-open on cache errors: a cache glitch must
# never block a legitimate first-time bind.

_LINK_TOKEN_USED_PREFIX = "tglink_used:"


def _extract_token_nonce(token: str) -> Optional[str]:
    """Pull the nonce out of a ``{b64uid}.{exp}.{nonce}.{sig}`` token."""
    parts = token.split(".", 3)
    return parts[2] if len(parts) == 4 else None


def _is_link_token_consumed(nonce: str) -> bool:
    try:
        return get_cache(f"{_LINK_TOKEN_USED_PREFIX}{nonce}") is not None
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 — fail-open, never block a real bind
        logger.warning("link-token consumed check failed (allowing): %s", exc)
        return False


def _mark_link_token_consumed(nonce: str, ttl_seconds: int) -> None:
    try:
        set_cache(f"{_LINK_TOKEN_USED_PREFIX}{nonce}", "1", ttl=max(ttl_seconds, 60))
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("link-token mark-consumed failed: %s", exc)


# ============================================================================
# Pydantic models
# ============================================================================


class LinkTokenResponse(BaseModel):
    token: str
    bot_username: str = Field(description="Bot @username to send /link to")
    expires_in: int = Field(description="Token TTL in seconds")


class VerifyLinkRequest(BaseModel):
    token: str
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None


class VerifyLinkResponse(BaseModel):
    success: bool
    user_id: str
    username: str


class TelegramStatusResponse(BaseModel):
    bound: bool
    telegram_id: Optional[int] = None
    telegram_username: Optional[str] = None
    linked_at: Optional[str] = None


class ChatRequest(BaseModel):
    telegram_id: int
    message: str
    language: str = "zh-TW"


class ChatResponse(BaseModel):
    success: bool
    response: str
    session_id: str


class SessionsRequest(BaseModel):
    telegram_id: int


class SessionItem(BaseModel):
    id: str
    title: str
    updated_at: Optional[str] = None
    is_active: bool = False


class SessionsResponse(BaseModel):
    success: bool
    sessions: list[SessionItem]
    active_session_id: Optional[str] = None


class UseSessionRequest(BaseModel):
    telegram_id: int
    # None / "" 表示切回預設的 tg:{telegram_id} 滾動 session。
    session_id: Optional[str] = None


class UseSessionResponse(BaseModel):
    success: bool
    active_session_id: Optional[str] = None


# ============================================================================
# Web-facing endpoints (require platform JWT)
# ============================================================================


@router.get("/status", response_model=TelegramStatusResponse)
async def get_telegram_status(current_user: dict = Depends(get_current_user)):
    """Check whether the current web user has a Telegram account bound."""
    binding = await run_sync(get_binding_by_user_id, current_user["user_id"])
    if not binding:
        return TelegramStatusResponse(bound=False)
    return TelegramStatusResponse(
        bound=True,
        telegram_id=binding["telegram_id"],
        telegram_username=binding.get("username"),
        linked_at=binding.get("linked_at"),
    )


@router.post("/link-token", response_model=LinkTokenResponse)
@limiter.limit("5/minute")
async def create_link_token(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Issue a short-lived link token for the current user.

    The user sends ``/link <token>`` to the bot to complete binding.
    """
    token = generate_link_token(current_user["user_id"])
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "").lstrip("@")
    return LinkTokenResponse(
        token=token,
        bot_username=bot_username,
        expires_in=LINK_TOKEN_TTL_SECONDS,
    )


@router.post("/unlink", response_model=TelegramStatusResponse)
@limiter.limit("5/minute")
async def unlink_telegram(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Remove the Telegram binding for the current user."""
    deleted = await run_sync(delete_binding_by_user_id, current_user["user_id"])
    logger.info(
        "Telegram unlink: user=%s deleted=%s",
        current_user["user_id"],
        deleted,
    )
    return TelegramStatusResponse(bound=False)


# ============================================================================
# Bot-facing endpoints (require X-Bot-Secret header)
# ============================================================================


@router.post("/verify-link", response_model=VerifyLinkResponse)
@limiter.limit("10/minute")
async def verify_link(
    request: Request,
    body: VerifyLinkRequest,
    _: None = Depends(_require_bot_secret),
):
    """Bot calls this after the user sends ``/link <token>``.

    The server tries the token against each candidate user_id by first
    looking up which user the bot thinks it is talking to via
    ``telegram_id``. If an existing binding exists, we re-bind. If not,
    we brute-force verify against all users — but since the token is
    HMAC-signed with user_id, we must know the user_id first.

    Practical flow: the bot passes the raw token. The server cannot
    reverse user_id from it (HMAC is one-way), so we require the bot
    to also pass ``telegram_id``. We then check if this telegram_id is
    already bound — if so, reject (already linked). If not, we look up
    users one by one... ⚠️ this is O(n).

    Better approach: embed a base64-encoded user_id hint in the token.
    """
    result = verify_link_token(body.token)
    if not result:
        raise HTTPException(status_code=400, detail="Invalid or expired link token.")
    matched_user_id, exp_ts = result

    # 一次性：拒絕已消費過的 token（防 5 分鐘內重放 → 帳號被綁走）。
    nonce = _extract_token_nonce(body.token)
    if nonce and await run_sync(_is_link_token_consumed, nonce):
        logger.warning("Telegram verify-link rejected: token replay nonce=%s", nonce)
        raise HTTPException(status_code=400, detail="Invalid or expired link token.")

    user = await run_sync(get_user_by_id, matched_user_id)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=403, detail="User account is not active.")

    # 不因 telegram_id 已綁定而拒絕（移除舊的 409）。create_telegram_binding 會以
    # telegram_id upsert 方式把綁定「移動」到本次 token 對應的帳號（= 重新綁定 /
    # 切換帳號），並清掉該帳號舊的 telegram 綁定。安全性：必須同時握有「該 Telegram」
    # （由 bot 端 /link 證明，使用者只能用自己的 Telegram 發送）與「目標帳號的有效
    # token」（由該帳號 web session 產生），無法竊取他人 Telegram。
    # 這也修復了：舊綁定殘留 → 網頁顯示未綁定卻無法重綁的卡死狀態。
    existing = await run_sync(get_binding_by_telegram_id, body.telegram_id)
    if existing and existing.get("user_id") != matched_user_id:
        logger.info(
            "Telegram re-bind: telegram_id=%s moving from user=%s to user=%s",
            body.telegram_id,
            existing.get("user_id"),
            matched_user_id,
        )

    ok = await run_sync(
        create_telegram_binding,
        body.telegram_id,
        matched_user_id,
        body.username,
        body.first_name,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to create binding.")

    # 綁定成功後才標記 token 已消費（失敗則 token 仍可重試，不會白白燒掉）。
    if nonce:
        await run_sync(_mark_link_token_consumed, nonce, exp_ts - int(time.time()))

    logger.info(
        "Telegram binding created: telegram_id=%s user_id=%s",
        body.telegram_id,
        matched_user_id,
    )
    return VerifyLinkResponse(
        success=True,
        user_id=matched_user_id,
        username=user["username"],
    )


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("10/minute")
async def bot_chat(
    request: Request,
    body: ChatRequest,
    _: None = Depends(_require_bot_secret),
):
    """Bot-facing chat endpoint.

    Resolves the Telegram binding, loads the user's BYOK api key,
    and runs the ManagerAgent graph directly. Returns the final
    response text (no SSE — the bot handles user-facing delivery).
    """
    # Lazy import to keep module import side-effects minimal.
    from api.routers.telegram_chat import run_telegram_chat

    try:
        return await run_telegram_chat(
            telegram_id=body.telegram_id,
            message=body.message,
            language=body.language,
        )
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("Telegram chat failed: %s", exc)
        raise HTTPException(status_code=500, detail="Chat processing failed.") from exc


def _tg_default_session_id(telegram_id: int) -> str:
    return f"tg:{telegram_id}"


@router.post("/sessions", response_model=SessionsResponse)
@limiter.limit("20/minute")
async def bot_list_sessions(
    request: Request,
    body: SessionsRequest,
    _: None = Depends(_require_bot_secret),
):
    """Bot-facing: list the linked user's chat sessions for /sessions."""
    binding = await run_sync(get_binding_by_telegram_id, body.telegram_id)
    if not binding:
        raise HTTPException(status_code=403, detail="NOT_BOUND")

    # ✅ 標記要跟「bot 實際會用的 session」一致：優先跨平台 current_session_id，
    # 其次 Telegram 釘選的 active_session_id，最後預設 —— 與 telegram_chat 的
    # 取用順序相同，避免清單標的對話與實際接續的對話不符。
    active = (
        await run_sync(get_current_session, binding["user_id"])
        or await run_sync(get_telegram_active_session, body.telegram_id)
        or _tg_default_session_id(body.telegram_id)
    )
    rows = await run_sync(get_sessions, binding["user_id"], 20, 0)
    sessions = [
        SessionItem(
            id=row["id"],
            title=row.get("title") or "New Chat",
            updated_at=row.get("updated_at"),
            is_active=row["id"] == active,
        )
        for row in rows
    ]
    return SessionsResponse(success=True, sessions=sessions, active_session_id=active)


@router.post("/use-session", response_model=UseSessionResponse)
@limiter.limit("20/minute")
async def bot_use_session(
    request: Request,
    body: UseSessionRequest,
    _: None = Depends(_require_bot_secret),
):
    """Bot-facing: switch the active session for /sessions selection.

    Passing an empty/None session_id resets to the default rolling
    ``tg:{telegram_id}`` session.
    """
    binding = await run_sync(get_binding_by_telegram_id, body.telegram_id)
    if not binding:
        raise HTTPException(status_code=403, detail="NOT_BOUND")

    target = (body.session_id or "").strip() or None
    default_id = _tg_default_session_id(body.telegram_id)

    # 切換到非預設 session 時，驗證該 session 確實屬於此使用者，
    # 避免透過 bot 讀取他人對話。
    if target and target != default_id:
        owns = await run_sync(check_session_ownership, target, binding["user_id"])
        if not owns:
            raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

    # 預設 session 以 NULL 儲存（fallback 行為），其餘存實際 id。
    stored = None if (target is None or target == default_id) else target
    ok = await run_sync(set_telegram_active_session, body.telegram_id, stored)
    if not ok:
        raise HTTPException(status_code=500, detail="UPDATE_FAILED")

    # 同步跨平台共用的當前對話 → 在 Telegram /sessions 選的對話，網頁端也跟著。
    await run_sync(set_current_session, binding["user_id"], stored or default_id)

    return UseSessionResponse(success=True, active_session_id=stored or default_id)
