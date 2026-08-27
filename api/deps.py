import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, TypedDict

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jwt import ExpiredSignatureError, InvalidTokenError

from core.orm.repositories import _normalize_membership_tier, user_repo

load_dotenv()
logger = logging.getLogger(__name__)

ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"


class CurrentUser(TypedDict, total=False):
    user_id: str
    username: str
    is_premium: bool
    membership_tier: str
    created_at: str
    is_active: bool
    role: str


# Configuration
# 🔒 Security: JWT_SECRET_KEY must be set via environment variable
# Generate a secure key: openssl rand -hex 32
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
REFRESH_TOKEN_EXPIRE_DAYS = 30  # 30 days for refresh tokens
_COOKIE_SECURE = os.getenv("ENVIRONMENT", "development").lower() in (
    "production",
    "prod",
)
_COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "")
_COOKIE_SAME_SITE = "Lax"

if not SECRET_KEY:
    raise ValueError(
        "🚨 SECURITY ERROR: JWT_SECRET_KEY environment variable is required.\n"
        "Generate a strong key using: openssl rand -hex 32\n"
        "Then set it in your .env file: JWT_SECRET_KEY=<your-key>"
    )
if len(SECRET_KEY) < 32:
    raise ValueError(
        "🚨 SECURITY ERROR: JWT_SECRET_KEY must be at least 32 characters long.\n"
        f"Current length: {len(SECRET_KEY)} characters.\n"
        "Generate a stronger key using: openssl rand -hex 32"
    )


# === Refresh Token Blacklist (Redis-preferred + file-backed fallback) ===
#
# GAP-2 根治:multi-worker 部署(gunicorn WEB_CONCURRENCY>1)下,in-memory +
# file-backed 的 revoke 不同步 — worker A 登出的 token,worker B 仍認。
#
# degrade-safe 設計:Redis 可用 → 走 Redis(跨 worker 共享,即時撤銷);
# Redis 不可用 → 自動退回既有 in-memory + file-backed(不破壞任何現有部署)。
# 一旦設了 REDIS_URL/REDIS_HOST 就自動受益,無須改其他設定。
#
# 為什麼用 sync redis client(非 async):revoke 不在 hot path(只登入驗證 +
# logout),單次 GET/SET ms 級;保持 is_token_revoked/revoke_token 的 sync 簽名,
# 零呼叫端改動(ws_auth.py、user.py 都直接用)。
_REVOKED_TOKENS_FILE = Path("data/revoked_tokens.json")
_revoked_tokens: dict[str, str] = {}  # token_hash -> ISO expiry string
_revoked_tokens_lock = threading.Lock()

# Redis client for token blacklist(lazy init;None = 未設/連不上 → degrade)
_revoked_redis: Optional["object"] = None
_revoked_redis_checked: bool = False

_REDIS_KEY_PREFIX = "revoked_token:"


def _get_revoked_redis_client():
    """取得 token blacklist 專用 Redis client。無 Redis / 連不上 → 回 None(degrade)。

    lazy + cached:第一次呼叫檢查 env 並嘗試連線,成功則快取;失敗設 _checked
    避免每次都重試(直到下次 process 重啟)。
    """
    global _revoked_redis, _revoked_redis_checked
    if _revoked_redis_checked:
        return _revoked_redis
    _revoked_redis_checked = True
    try:
        from core.redis_url import resolve_redis_url

        redis_url, source = resolve_redis_url()
        if not redis_url or source == "":
            return None  # 未設 REDIS_URL/REDIS_HOST
        import redis  # sync client

        client = redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2)
        client.ping()  # 驗證連線
        _revoked_redis = client
        logger.info("Token blacklist: using Redis (%s) for cross-worker revoke sync", source)
        return _revoked_redis
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning(
            "Token blacklist: Redis unavailable (%s), degrading to file-backed "
            "(multi-worker revoke may not sync)",
            exc,
        )
        return None


def _load_revoked_tokens() -> None:
    """Load persisted revoked tokens from disk into memory on startup."""
    try:
        if _REVOKED_TOKENS_FILE.exists():
            with open(_REVOKED_TOKENS_FILE, "r", encoding="utf-8") as f:
                raw: dict = json.load(f)
            now = datetime.now(timezone.utc)
            # Only load non-expired entries
            _revoked_tokens.update(
                {h: exp for h, exp in raw.items() if datetime.fromisoformat(exp) > now}
            )
    except Exception as exc:
        logger.warning("Failed to load revoked tokens from disk: %s", exc)


def _save_revoked_tokens() -> None:
    """Persist current revoked tokens to disk (must be called under lock)."""
    try:
        _REVOKED_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_REVOKED_TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(_revoked_tokens, f)
    except Exception as exc:
        logger.warning("Failed to persist revoked tokens to disk: %s", exc)


# Load existing revocations at import time
_load_revoked_tokens()


def _hash_token(token: str) -> str:
    """Create a SHA-256 hash of a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def revoke_token(token: str, expires_at: Optional[datetime] = None) -> None:
    """Revoke a refresh token by adding its hash to the blacklist.

    Redis-preferred(跨 worker 即時撤銷);無 Redis 退回 in-memory + file。
    Also opportunistically prunes already-expired entries so storage doesn't
    grow unboundedly.
    """
    token_hash = _hash_token(token)
    expiry = expires_at or (
        datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )
    expiry_iso = expiry.isoformat()

    # 1. 先試 Redis(跨 worker 共享)
    client = _get_revoked_redis_client()
    if client is not None:
        try:
            ttl_seconds = int((expiry - datetime.now(timezone.utc)).total_seconds())
            if ttl_seconds > 0:
                client.set(_REDIS_KEY_PREFIX + token_hash, expiry_iso, ex=ttl_seconds)
                logger.info(f"Token revoked (Redis): {token_hash[:16]}...")
                return
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            logger.warning("Redis revoke failed, falling back to file: %s", exc)

    # 2. fallback: in-memory + file
    with _revoked_tokens_lock:
        now = datetime.now(timezone.utc)
        expired = [
            h for h, exp in _revoked_tokens.items() if datetime.fromisoformat(exp) < now
        ]
        for h in expired:
            del _revoked_tokens[h]
        _revoked_tokens[token_hash] = expiry_iso
        _save_revoked_tokens()
    logger.info(f"Token revoked (file): {token_hash[:16]}...")


def is_token_revoked(token: str) -> bool:
    """Check if a token has been revoked.

    Redis-preferred(跨 worker 即時查詢);無 Redis 退回 in-memory + file。
    """
    token_hash = _hash_token(token)

    # 1. 先試 Redis
    client = _get_revoked_redis_client()
    if client is not None:
        try:
            if client.exists(_REDIS_KEY_PREFIX + token_hash):
                return True
            # Redis 查無 → 也檢查本地 file(防剛切換到 Redis 時舊條目漏遷)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            logger.warning("Redis revoke check failed, falling back to file: %s", exc)
            # 連線壞了 → 退 file,別讓 auth 因 Redis 故障而放行

    # 2. fallback: in-memory + file(也涵蓋 Redis 查無時的舊條目檢查)
    with _revoked_tokens_lock:
        if token_hash in _revoked_tokens:
            expiry = datetime.fromisoformat(_revoked_tokens[token_hash])
            if expiry < datetime.now(timezone.utc):
                del _revoked_tokens[token_hash]
                _save_revoked_tokens()
                return False
            return True
    return False


def cleanup_expired_revoked_tokens() -> int:
    """Remove expired entries from the revoked tokens blacklist. Returns count removed."""
    removed = 0
    now = datetime.now(timezone.utc)
    with _revoked_tokens_lock:
        expired = [
            h for h, exp in _revoked_tokens.items() if datetime.fromisoformat(exp) < now
        ]
        for h in expired:
            del _revoked_tokens[h]
            removed += 1
        if removed:
            _save_revoked_tokens()
    if removed:
        logger.info(f"Cleaned up {removed} expired revoked tokens")
    return removed


async def revoked_tokens_cleanup_task():
    """Periodic background task: prune expired revoked tokens hourly.

    revoke_token() opportunistic-ally prunes on each logout, but if users
    only log out rarely (or never), the in-memory dict + on-disk JSON would
    grow forever. This task guarantees bounded growth regardless of traffic.
    """
    import asyncio

    while True:
        await asyncio.sleep(3600)  # hourly
        try:
            # L3 修復（2026-07-20）：cleanup_expired_revoked_tokens 內部做
            # in-memory dict prune + _save_revoked_tokens 寫 JSON 檔到磁碟。
            # 過去直接呼叫會凍結 event loop（雖然檔案小、每小時才跑一次）。
            from api.utils import run_sync

            await run_sync(cleanup_expired_revoked_tokens)
        except Exception as exc:
            logger.warning("revoked_tokens_cleanup_task error: %s", exc)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/user/login", auto_error=False)


def _is_expected_user_db_fallback_error(exc: Exception) -> bool:
    if isinstance(exc, ModuleNotFoundError):
        return True
    message = str(exc)
    return "async_generator" in message and "context manager" in message


def set_token_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    """Set httpOnly cookies for JWT tokens."""
    kwargs: dict = {
        "secure": _COOKIE_SECURE,
        "httponly": True,
        "samesite": _COOKIE_SAME_SITE,
        "path": "/",
    }
    if _COOKIE_DOMAIN:
        kwargs["domain"] = _COOKIE_DOMAIN

    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **kwargs,
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        **kwargs,
    )


def clear_token_cookies(response: Response) -> None:
    """Clear JWT cookies on logout."""
    kwargs: dict = {"path": "/"}
    if _COOKIE_DOMAIN:
        kwargs["domain"] = _COOKIE_DOMAIN
    response.delete_cookie(ACCESS_TOKEN_COOKIE, **kwargs)
    response.delete_cookie(REFRESH_TOKEN_COOKIE, **kwargs)


def get_token_from_cookie(request: Request) -> Optional[str]:
    """Extract access token from httpOnly cookie, falling back to Bearer header."""
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if cookie_token:
        return cookie_token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def resolve_request_token(request: Request, bearer_token: Optional[str]) -> str:
    """
    Resolve the access token for an authenticated request.

    Prefer the httpOnly cookie over the Authorization header so a stale
    in-memory bearer token cannot override a freshly refreshed browser session.
    """
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if cookie_token:
        return cookie_token
    return bearer_token or ""


def best_effort_request_user(request: Request) -> Optional[dict]:
    """Best-effort 解析請求的 user（供 middleware 在 DI 之前識別 user）。

    正式站 auth 走 FastAPI DI（Depends(get_current_user)），DI 之前跑的 middleware
    （audit / rate limit）看不到 user。這裡 best-effort 解 access_token cookie/Bearer
    的 JWT 拿 sub（user_id），不驗證 revocation、不擋請求（DI 仍是最終認證）。

    Returns:
        dict with user_id/username，或 None（未認證/解失敗）。
    """
    try:
        auth_header = request.headers.get("Authorization", "")
        bearer = auth_header[7:] if auth_header.startswith("Bearer ") else None
        token = resolve_request_token(request, bearer)
        if not token:
            return None
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id:
            return {
                "user_id": user_id,
                "username": payload.get("username", user_id),
            }
    except Exception:
        # token 無效/過期/不存在 → 未認證；不記 warning 避免洗 log
        pass
    return None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a new JWT access token."""
    to_encode = data.copy()
    to_encode["type"] = "access"
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Create a new JWT refresh token with longer expiration."""
    to_encode = data.copy()
    to_encode["type"] = "refresh"
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(
        days=REFRESH_TOKEN_EXPIRE_DAYS
    )
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """
    Verify the token and return the payload.
    Used for WebSocket authentication or where Depends() cannot be used.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )


async def get_current_user_id(
    request: Request, token: str = Depends(oauth2_scheme)
) -> str:
    """
    Validate the token and return the user_id.
    Reads from httpOnly cookie first, falls back to Authorization header.
    """
    resolved_token = resolve_request_token(request, token)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not resolved_token:
        raise credentials_exception

    try:
        payload = jwt.decode(resolved_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return user_id
    except (InvalidTokenError, HTTPException):
        raise credentials_exception


async def get_current_user(
    request: Request, token: str = Depends(oauth2_scheme)
) -> CurrentUser:
    """
    Validate token and return full user dict.
    Reads from httpOnly cookie first, falls back to Authorization header.
    In TEST_MODE, automatically return test user without requiring valid token.
    """
    from core.config import TEST_MODE, TEST_USER

    # 安全檢查：禁止在生產環境啟用 TEST_MODE
    if TEST_MODE:
        env = os.getenv("ENVIRONMENT", "development").lower()
        if env in ["production", "prod"]:
            raise ValueError(
                "🚨 SECURITY ALERT: TEST_MODE must not be enabled in production environment"
            )

    resolved_token = resolve_request_token(request, token)
    user_id = None

    if resolved_token:
        if TEST_MODE and resolved_token.startswith("test-user-"):
            _allowed = {
                u.strip()
                for u in os.getenv("ALLOWED_TEST_USERS", "test-user-001").split(",")
                if u.strip()
            }
            if resolved_token in _allowed:
                user_id = resolved_token
        else:
            try:
                payload = jwt.decode(resolved_token, SECRET_KEY, algorithms=[ALGORITHM])
                user_id = payload.get("sub")
                if not user_id and not TEST_MODE:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Could not validate credentials",
                    )
            except ExpiredSignatureError:
                if not TEST_MODE:
                    raise
                user_id = None
            except (InvalidTokenError, HTTPException):
                if not TEST_MODE:
                    raise
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Could not validate credentials",
                )

    if user_id:
        try:
            user = await user_repo.get_by_id(user_id)
            if user:
                if not user.get("is_active", True):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Account has been suspended",
                    )
                return user
        except HTTPException:
            raise
        except Exception as exc:
            if _is_expected_user_db_fallback_error(exc):
                logger.warning(
                    "Failed to load current user from DB; falling back by mode: %s",
                    exc,
                )
            else:
                logger.warning(
                    "Failed to load current user from DB; falling back by mode",
                    exc_info=True,
                )

    if TEST_MODE:
        if not user_id:
            user_id = TEST_USER.get("uid", "test-user-001")

        # 即使在 TEST_MODE，若該帳號確實存在於 DB 且被停權（is_active=False），
        # 仍應拒絕——避免管理員停權的帳號透過 TEST_MODE fallback 繞過。
        # 僅當查不到／DB 不可用時才放行（開發環境容錯）。
        try:
            _existing = await user_repo.get_by_id(user_id)
            if _existing and not _existing.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account has been suspended",
                )
        except HTTPException:
            raise
        except Exception:
            # DB 不可用或帳號不存在：開發環境下放行
            pass

        test_tier = _normalize_membership_tier(
            os.environ.get("TEST_USER_TIER", "premium")
        )

        return {
            "user_id": user_id,
            "username": f"TestUser_{user_id[-3:]}",
            "is_premium": test_tier == "premium",
            "membership_tier": test_tier,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_optional_current_user(
    request: Request, token: str = Depends(oauth2_scheme)
) -> Optional[CurrentUser]:
    """
    Best-effort user resolution for endpoints that may be viewed anonymously.
    Returns the authenticated user when credentials are valid, otherwise None.
    """
    resolved_token = resolve_request_token(request, token)
    if not isinstance(resolved_token, str) or not resolved_token:
        return None

    try:
        return await get_current_user(request, resolved_token)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return None
        raise


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Require admin role. Use as dependency on admin-only endpoints."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    if not current_user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )
    return current_user
