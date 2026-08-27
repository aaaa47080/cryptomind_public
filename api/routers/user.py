import asyncio
from typing import Optional

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from slowapi.util import get_remote_address

from api.deps import (
    clear_token_cookies,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_optional_current_user,
    set_token_cookies,
)
from api.middleware.rate_limit import limiter
from api.models import (
    AnalysisPreferenceInput,
    WatchlistRequest,
)
from api.utils import logger, run_sync
from core.audit import audit_log
from core.config import TEST_MODE, TEST_USER
from core.database import (
    add_to_watchlist,
    create_or_get_user,
    get_user_wallet_status,
    get_watchlist,
    remove_from_watchlist,
    save_user_feedback,
)
from core.database.user import (
    get_user_by_id,
    is_display_name_taken,
    is_username_taken,
    set_user_display_name,
    upgrade_to_pro,
)
from core.orm.repositories import user_repo
from core.orm.user_api_keys_repo import LLM_PROVIDERS
from core.orm.user_llm_preferences_repo import user_llm_preferences_repo

router = APIRouter()


@router.get("/api/watchlist")
async def get_user_watchlist(current_user: dict = Depends(get_current_user)):
    """獲取用戶的自選清單"""
    try:
        user_id = current_user["user_id"]
        symbols = await run_sync(get_watchlist, user_id)
        return {"symbols": symbols}
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"獲取自選清單失敗: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch watchlist")


@router.post("/api/watchlist/add")
@limiter.limit("20/minute")
async def add_watchlist(
    request: Request,
    req: WatchlistRequest,
    current_user: dict = Depends(get_current_user),
):
    """新增幣種到自選清單"""
    try:
        user_id = current_user["user_id"]
        current_list = await run_sync(get_watchlist, user_id)
        if len(current_list) >= 10:
            raise HTTPException(
                status_code=400,
                detail="Watchlist is full (max 10). Remove an existing symbol and try again.",
            )

        await run_sync(add_to_watchlist, user_id, req.symbol.upper())
        return {"success": True, "message": f"{req.symbol} added to watchlist"}
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"新增自選清單失敗: {e}")
        raise HTTPException(status_code=500, detail="Failed to add")


@router.post("/api/watchlist/remove")
@limiter.limit("20/minute")
async def remove_watchlist(
    request: Request,
    req: WatchlistRequest,
    current_user: dict = Depends(get_current_user),
):
    """從自選清單移除幣種"""
    try:
        user_id = current_user["user_id"]
        await run_sync(remove_from_watchlist, user_id, req.symbol.upper())
        return {"success": True, "message": f"{req.symbol} removed from watchlist"}
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"移除自選清單失敗: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove")


# --- Dev/Test Login Endpoint ---


class DevLoginRequest(BaseModel):
    user_id: Optional[str] = None
    confirmation: str = Field(
        "I_UNDERSTAND_THE_RISKS", description='Must be "I_UNDERSTAND_THE_RISKS"'
    )

    def model_post_init(self, __context):
        if self.confirmation != "I_UNDERSTAND_THE_RISKS":
            raise ValueError('confirmation must be "I_UNDERSTAND_THE_RISKS"')


class UserFeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="zh-TW")


@router.post("/api/user/dev-login")
@limiter.limit("5/minute")
async def dev_login(request: Request, response: Response, body: DevLoginRequest = None):
    """
    僅在 TEST_MODE=True 時可用的開發測試登入
    返回測試用戶的 JWT Token
    可選：傳入 user_id 以切換到特定測試用戶
    """
    if not TEST_MODE:
        raise HTTPException(status_code=403, detail="Test mode is disabled")

    if body and body.user_id:
        test_user_id = body.user_id
        suffix = (
            test_user_id.split("-")[-1] if "-" in test_user_id else test_user_id[-3:]
        )
        test_username = f"TestUser_{suffix}"
    else:
        test_user_id = TEST_USER.get("uid", "test-user-001")
        test_username = TEST_USER.get("username", "TestUser")

    access_token = create_access_token(
        data={"sub": test_user_id, "username": test_username}
    )
    refresh_token = create_refresh_token(
        data={"sub": test_user_id, "username": test_username}
    )

    try:
        existing_user = await run_sync(get_user_by_id, test_user_id)
        if not existing_user:
            await run_sync(create_or_get_user, test_user_id, test_username)
            logger.info(
                f"[DEV LOGIN] Created missing mock user {test_username} ({test_user_id}) in DB."
            )

        # Test accounts default to Premium so the full feature set (custom
        # System Prompt, tool toggles, etc.) is exercisable without manually
        # picking a special user id. TEST_MODE only — never reached in prod.
        await run_sync(upgrade_to_pro, test_user_id, 12, None)

    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"[DEV LOGIN] Error ensuring test user exists: {e}")

    set_token_cookies(response, access_token, refresh_token)

    return {
        "success": True,
        "user": {
            "uid": test_user_id,
            "username": test_username,
            "authMethod": "dev_test",
        },
    }


# --- TON Connect Endpoints (Web DApp) ---


@router.get("/api/user/ton-proof-payload")
@limiter.limit("30/minute")
async def ton_proof_payload(request: Request):
    """Issue a fresh nonce for the wallet to sign during connect (ton_proof)."""
    from api.ton_verification import generate_ton_proof_payload

    return {"payload": generate_ton_proof_payload()}


class TonProof(BaseModel):
    timestamp: int
    domain: dict | str
    payload: str
    signature: str


class TonLoginRequest(BaseModel):
    address: str  # user-friendly address (UQ/0Q...) — used as identity
    raw_address: str  # raw "0:hex" — used for proof verification
    public_key: str
    network: Optional[str] = None
    proof: TonProof


@router.post("/api/user/ton-login")
@limiter.limit("10/minute")
async def ton_login(request: Request, response: Response, body: TonLoginRequest):
    """
    Authenticate a TON wallet via TON Connect ton_proof.

    Verifies wallet ownership (ed25519 proof) then issues the same JWT session
    cookies used by the Pi flow, with the wallet address as the user identity.
    """
    from api.ton_verification import verify_ton_proof

    # GAP-1: TON proof 驗證失敗也記錄(可能是偽造 proof / replay 攻擊)。
    from core.auth_failure_tracker import record_auth_failure

    client_ip = get_remote_address(request)

    proof = body.proof
    domain_val = (
        proof.domain.get("value") if isinstance(proof.domain, dict) else proof.domain
    )

    # H7 修復（2026-07-20）：verify_ton_proof 內部呼叫 sync httpx.Client 打
    # TONCENTER runGetMethod（最多 10s）。過去直接在 async route 內呼叫會凍結
    # event loop。每次 TON 登入都會卡住整個 worker。
    from api.utils import run_sync

    try:
        await run_sync(
            lambda: verify_ton_proof(
                address=body.raw_address,
                public_key=body.public_key,
                domain=domain_val or "",
                timestamp=int(proof.timestamp),
                payload=proof.payload,
                signature=proof.signature,
            )
        )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as proof_err:
        record_auth_failure(client_ip, f"ton proof invalid: {type(proof_err).__name__}")
        raise

    # Identity = friendly wallet address; derive a readable default username.
    ton_uid = body.address
    username = "TON_" + body.address[2:8]

    try:
        result = await run_sync(
            lambda: create_or_get_user(identity=ton_uid, username=username)
        )

        access_token = create_access_token(
            data={"sub": result["user_id"], "username": result["username"]}
        )
        refresh_token = create_refresh_token(
            data={"sub": result["user_id"], "username": result["username"]}
        )
        set_token_cookies(response, access_token, refresh_token)

        # 訪客追蹤：記錄錢包連接事件（後台 Visitors 分頁資料來源）。
        # 只記 ton_proof 驗證成功的真連接；metadata 含 address/is_new/ip 供審計。
        audit_log(
            action="wallet_connected",
            user_id=result["user_id"],
            username=result["username"],
            metadata={
                "wallet_address": body.address,
                "is_new_user": result.get("is_new", False),
                "ip": client_ip,
            },
        )

        return {
            "success": True,
            "user": {
                "user_id": result["user_id"],
                "username": result["username"],
                "auth_method": result.get("auth_method", "ton_wallet"),
                "role": result.get("role", "user"),
                "membership_tier": result.get("membership_tier", "free"),
                "has_wallet": True,
                "wallet_address": body.address,
            },
            "is_new_user": result.get("is_new", False),
        }
    except ValueError as e:
        logger.warning("TON 用戶同步失敗 - 用戶名衝突: %s", e)
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error("TON 用戶同步失敗: %s", e)
        raise HTTPException(status_code=500, detail="Sync failed")


class TelegramLoginRequest(BaseModel):
    init_data: str  # window.Telegram.WebApp.initData (signed by Telegram)


@router.post("/api/user/telegram-login")
@limiter.limit("20/minute")
async def telegram_login(
    request: Request, response: Response, body: TelegramLoginRequest
):
    """
    Authenticate a Telegram Mini App user via signed ``initData``.

    Telegram already vouches for the user's identity, so no wallet signature
    is needed to log in. Resolution:
      - If this telegram_id is already bound (via /link or a prior login),
        log in as that existing account (which may have a wallet).
      - Otherwise auto-create a Telegram-native account (identity=tg_<id>)
        and bind it. The user can connect a wallet later for TON payments.
    """
    from api.telegram_verification import verify_telegram_init_data

    # GAP-1: Telegram initData 驗證失敗也記錄(可能是偽造簽章)。
    from core.auth_failure_tracker import record_auth_failure
    from core.database.telegram import (
        create_telegram_binding,
        get_binding_by_telegram_id,
    )

    client_ip = get_remote_address(request)

    try:
        tg_user = verify_telegram_init_data(body.init_data)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as verify_err:
        record_auth_failure(client_ip, f"telegram init_data invalid: {type(verify_err).__name__}")
        raise
    tg_id = int(tg_user["id"])
    tg_username = tg_user.get("username") or None
    tg_first = tg_user.get("first_name") or None

    try:
        binding = await run_sync(lambda: get_binding_by_telegram_id(tg_id))
        if binding and binding.get("user_id"):
            # Existing linked account (may be wallet-based or a prior tg_ login).
            identity = binding["user_id"]
            result = await run_sync(lambda: create_or_get_user(identity=identity))
        else:
            # First time: create a Telegram-native account and bind it.
            identity = f"tg_{tg_id}"
            username = tg_username or (f"TG_{tg_first}" if tg_first else f"TG_{tg_id}")
            result = await run_sync(
                lambda: create_or_get_user(
                    identity=identity, username=username, auth_method="telegram"
                )
            )
            await run_sync(
                lambda: create_telegram_binding(
                    tg_id, result["user_id"], tg_username, tg_first
                )
            )

        access_token = create_access_token(
            data={"sub": result["user_id"], "username": result["username"]}
        )
        refresh_token = create_refresh_token(
            data={"sub": result["user_id"], "username": result["username"]}
        )
        set_token_cookies(response, access_token, refresh_token)

        has_wallet = not str(result["user_id"]).startswith("tg_")
        return {
            "success": True,
            "user": {
                "user_id": result["user_id"],
                "username": result["username"],
                "auth_method": result.get("auth_method", "telegram"),
                "role": result.get("role", "user"),
                "membership_tier": result.get("membership_tier", "free"),
                "has_wallet": has_wallet,
            },
            "is_new_user": result.get("is_new", False),
        }
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error("Telegram 登入失敗: %s", e)
        raise HTTPException(status_code=500, detail="Telegram login failed")


# GET /api/user/me 回應快取（30s per-user TTL）。
# /me 被前端高頻呼叫（page-load + i18n 三事件 fan-out，~33/min），每次 2 個 run_sync
# 搶 shared DB executor；Zeabur postgres 偶發慢時 executor 被佔死 → timeout 500
# （2026-08-12 事件）。回應對同一 user 在 TTL 內穩定；下方 setter（語言/暱稱/LLM
# provider）主動 invalidate，改動後即時生效（不必等 TTL）。
_ME_CACHE: TTLCache = TTLCache(maxsize=2048, ttl=30)


@router.get("/api/user/me")
async def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """獲取當前登入用戶的資料（30s per-user TTL 快取，setter 主動 invalidate）。"""
    user_id = current_user.get("user_id")
    # 快取命中：直接回，避免 DB round-trip 與 thread pool
    cached = _ME_CACHE.get(user_id) if user_id else None
    if cached is not None:
        return cached
    language = await user_repo.get_language(user_id) if user_id else None
    display_name = (
        await user_repo.get_display_name(user_id) if user_id else None
    )
    # 使用者選的 LLM provider（跨裝置帶回）。None = 從未設定過，前端走既有 fallback。
    selected_provider = (
        await user_llm_preferences_repo.get_selected_provider(user_id)
        if user_id
        else None
    )

    # TON 用戶的 user_id 即錢包地址（已通過 ton_proof 驗證）。
    # auth_method 來自 DB；TEST_MODE fallback 不帶此欄位時，用 user_id 前綴
    # （UQ/EQ/0:）輔助判定，避免把 tg_<id> 誤認為錢包地址。
    auth_method = current_user.get("auth_method")
    if auth_method == "ton_wallet":
        wallet_address = user_id
    elif isinstance(user_id, str) and (
        user_id.startswith(("UQ", "EQ", "0:", "kQ"))
    ):
        wallet_address = user_id
    else:
        wallet_address = None

    response = {
        "success": True,
        "user": {
            "user_id": user_id,
            "username": current_user.get("username"),
            "role": current_user.get("role", "user"),
            "auth_method": auth_method,
            "membership_tier": current_user.get("membership_tier", "free"),
            "has_wallet": bool(current_user.get("has_wallet", True)),
            "language": language,
            # c010: 個人化暱稱（NULL = 未設定，前端 fallback 到 username）
            "display_name": display_name,
            # 已驗證的錢包地址（Trustworthy AI — Principal: agent 知道在跟誰對話）
            "wallet_address": wallet_address,
            # 使用者上次選的 LLM provider（跨裝置還原）。None = 從未設定。
            "selected_provider": selected_provider,
        },
    }
    if user_id:
        _ME_CACHE[user_id] = response
    return response


# ============================================================================
# 使用者選的 LLM provider（跨裝置帶回）
#
# 背景：selectedProvider 原本只存瀏覽器 localStorage，換裝置/清快取即失，
# 系統改按 provider 清單順序挑（openrouter 在 deepseek 前），導致使用者明明
# 選了 deepseek 卻被帶回 openrouter（額度用完時連帶讓聊天/釐清等功能失效）。
# 詳見 docs/plans/2026-08-06-persist-user-selected-provider-design.md。
# ============================================================================


class UserLLMProviderInput(BaseModel):
    provider: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="使用者選的 LLM provider（須在支援清單內）",
    )


@router.put("/api/user/preferences/llm-provider")
@limiter.limit("30/minute")
async def set_user_llm_provider_pref(
    request: Request,
    body: UserLLMProviderInput,
    current_user: dict = Depends(get_current_user),
):
    """儲存使用者選的 LLM provider（跨裝置帶回）。

    不檢查該 provider 是否已綁金鑰——前端切換時可能先選再綁 key；
    使用時 ``getCurrentProvider`` 仍會在 selected provider 無 key 時 fallback。
    """
    provider = (body.provider or "").strip().lower()
    if provider not in LLM_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider. Must be one of: {', '.join(LLM_PROVIDERS)}",
        )
    await user_llm_preferences_repo.set_selected_provider(
        current_user["user_id"], provider
    )
    _ME_CACHE.pop(current_user["user_id"], None)
    return {"success": True, "provider": provider}


# 支援的 UI 語言（與前端 LanguageSwitcher / i18n 對齊）
_SUPPORTED_LANGUAGES = {"zh-TW", "zh-CN", "en", "ru"}


class UserLanguageInput(BaseModel):
    language: str


@router.put("/api/user/language")
@limiter.limit("30/minute")
async def set_user_language_pref(
    request: Request,
    body: UserLanguageInput,
    current_user: dict = Depends(get_current_user),
):
    """儲存使用者的 UI 語言偏好（跨裝置 + 給 Telegram 共用）。"""
    from core.database.user import set_user_language

    lang = (body.language or "").strip()
    if lang not in _SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language. Must be one of: {', '.join(sorted(_SUPPORTED_LANGUAGES))}",
        )

    ok = await run_sync(set_user_language, current_user["user_id"], lang)
    if not ok:
        raise HTTPException(status_code=500, detail="save failed")
    _ME_CACHE.pop(current_user["user_id"], None)
    return {"success": True, "language": lang}


# ============================================================================
# 個人化暱稱（display_name）— Trustworthy AI Hackathon
#
# 讓使用者把預設代稱（TON_<hex>）改成自己想要的暱稱，chat 招呼與 Agent
# system prompt 才能個人化（Principal: agent 知道在跟誰對話）。
#
# 免費改名一次 / 24h；Phase 2 會加「付 TON 立即改名」繞過冷卻。
# ============================================================================


class UserDisplayNameInput(BaseModel):
    display_name: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="個人化暱稱（1–20 字，不可含換行/控制字元）",
    )


@router.put("/api/user/display-name")
@limiter.limit("5/minute")
async def set_user_display_name_pref(
    request: Request,
    body: UserDisplayNameInput,
    current_user: dict = Depends(get_current_user),
):
    """設定個人化暱稱，含 24h 免費改名冷卻。

    - 成功 → 200 + 新暱稱
    - 24h 內重複 → 429 + ``reason="cooldown"`` + ``next_available_at``
    - 內容不合法（空、過長、含換行/控制字元）→ 422
    - 暱稱已被他人使用 → 409 + ``reason="duplicate"``
    - 暱稱使用系統預設名格式（``TON_`` 開頭）→ 422 + ``reason="reserved"``
    """
    import re

    name = (body.display_name or "").strip()
    if not name or len(name) > 20:
        raise HTTPException(status_code=422, detail="display_name invalid")
    # 擋控制字元 / 換行（\r \n \t 與其他 C0/C1 control codes）
    if re.search(r"[\x00-\x1f\x7f-\x9f]", name):
        raise HTTPException(status_code=422, detail="display_name invalid")

    # 禁止系統預設名格式:TON_ 開頭是自動產生的識別(見 create_or_get_user),
    # 使用者取相同會造成「預設名 vs 自取名」混淆。也不可等於任何人的 username。
    if name.startswith("TON_"):
        raise HTTPException(
            status_code=422,
            detail={"reason": "reserved", "message": "Cannot use the system default name format (starting with TON_)"},
        )

    user_id = current_user["user_id"]

    # 預檢查:暱稱是否已被他人使用(DB 唯一索引做最終把關,此處提前擋以給清楚錯誤)
    if await run_sync(is_display_name_taken, name, user_id):
        raise HTTPException(
            status_code=409,
            detail={"reason": "duplicate", "message": "This display name is already taken"},
        )
    # 不可等於任何人的 username(系統預設名)
    if await run_sync(is_username_taken, name):
        raise HTTPException(
            status_code=422,
            detail={"reason": "reserved", "message": "This name is reserved by the system and cannot be used"},
        )

    result = await run_sync(set_user_display_name, user_id, name)
    ok = result[0]
    reason = result[1] if len(result) > 1 else None

    if ok:
        # /me 回應快取的 display_name 已變，主動 invalidate（見 _ME_CACHE）
        _ME_CACHE.pop(user_id, None)
        # 清除舊 greeting 快取,避免改名後歡迎訊息仍顯示舊暱稱長達 1 小時
        # lazy import 避免 router 模組間頂層耦合
        from api.routers.analysis import invalidate_greeting_cache

        invalidate_greeting_cache(user_id)

        # audit：rename 屬敏感操作（身份變更），記錄可追溯（audit_log 為 sync）
        audit_log(
            "rename_display_name",
            user_id=user_id,
            username=current_user.get("username"),
            resource_type="user",
            resource_id=user_id,
            request_data={"new_name": name},
            success=True,
        )
        return {"success": True, "display_name": name}

    if reason == "duplicate":
        # 競態:預檢查與 UPDATE 之間有人搶先取走同名
        raise HTTPException(
            status_code=409,
            detail={"reason": "duplicate", "message": "This display name is already taken"},
        )

    if reason == "cooldown":
        next_available = result[2] if len(result) > 2 else None
        # audit 失敗嘗試（可疑：可能是繞過冷卻的濫用）
        audit_log(
            "rename_display_name",
            user_id=user_id,
            username=current_user.get("username"),
            resource_type="user",
            resource_id=user_id,
            request_data={"new_name": name},
            success=False,
            error_message="cooldown",
        )
        raise HTTPException(
            status_code=429,
            detail={
                "reason": "cooldown",
                "message": "You can change it for free only once every 24 hours. Please try again later.",
                "next_available_at": next_available,
            },
        )

    # db_error 或其他
    raise HTTPException(status_code=500, detail="save failed")


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/api/user/refresh")
# 30/min：access token 過期時 limiter key 退化為 IP（共享 NAT 會互撞）；
# 前端 visibility/pageShow/30-min 多路徑皆可能觸發主動刷新，10/min 實測會 429
# （2026-08-14 平台測試觀察）。JWT re-issue 本身輕量，30/min 仍具暴力防護。
@limiter.limit("30/minute")
async def refresh_access_token(
    request: Request, response: Response, body: RefreshTokenRequest = None
):
    """
    使用 refresh token 獲取新的 access token。
    Reads refresh_token from cookie first, falls back to request body.
    """
    from api.deps import REFRESH_TOKEN_COOKIE, verify_token

    # GAP-1: auth 失敗自動偵測。失敗時記錄,達閾值發 BRUTE_FORCE_ATTEMPT event。
    from core.auth_failure_tracker import record_auth_failure

    client_ip = get_remote_address(request)

    refresh_token_value = body.refresh_token if body and body.refresh_token else None
    if not refresh_token_value:
        refresh_token_value = request.cookies.get(REFRESH_TOKEN_COOKIE)

    if not refresh_token_value:
        record_auth_failure(client_ip, "refresh token missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is required",
        )

    # Check if the refresh token has been revoked (e.g., from logout)
    from api.deps import is_token_revoked

    if is_token_revoked(refresh_token_value):
        record_auth_failure(client_ip, "refresh token revoked")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    try:
        payload = verify_token(refresh_token_value)
        if payload.get("type") != "refresh":
            record_auth_failure(client_ip, "invalid refresh token type")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        user_id = payload.get("sub")
        username = payload.get("username")

        if not user_id:
            record_auth_failure(client_ip, "invalid token payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        new_access_token = create_access_token(
            data={"sub": user_id, "username": username}
        )
        new_refresh_token = create_refresh_token(
            data={"sub": user_id, "username": username}
        )

        set_token_cookies(response, new_access_token, new_refresh_token)

        return {
            "success": True,
        }
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        record_auth_failure(client_ip, f"refresh exception: {type(e).__name__}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token refresh failed",
        )


@router.post("/api/user/logout")
@limiter.limit("30/minute")
async def logout(request: Request, response: Response):
    """Clear JWT cookies on logout and revoke refresh token."""
    from api.deps import REFRESH_TOKEN_COOKIE, revoke_token

    # Revoke the refresh token to prevent token reuse after logout
    refresh_token_value = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if refresh_token_value:
        revoke_token(refresh_token_value)

    clear_token_cookies(response)
    return {"success": True}


# --- Pi Payment Handling Endpoints ---


class ClientLogRequest(BaseModel):
    source: str = Field(..., description="Log source (e.g., 'premium', 'forum')")
    level: str = Field(default="info", description="Log level")
    message: str = Field(..., description="Log message")
    data: Optional[dict] = Field(default=None, description="Additional data")


_VALID_CLIENT_LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})


@router.post("/api/client/log")
@limiter.limit("30/minute")
async def client_log(
    request: Request,
    body: ClientLogRequest, current_user: dict = Depends(get_current_user)
):
    """接收前端 client-side logs 並寫入 server logs"""
    user_id = current_user.get("user_id", "unknown")
    safe_level = (
        body.level.lower() if body.level.lower() in _VALID_CLIENT_LOG_LEVELS else "info"
    )
    safe_source = body.source.replace("\n", " ").replace("\r", " ")
    safe_message = body.message.replace("\n", " ").replace("\r", " ")
    log_msg = f"[CLIENT:{safe_source}] [{safe_level.upper()}] {safe_message}"

    if body.data:
        safe_data = str(body.data).replace("\n", " ").replace("\r", " ")
        log_msg += f" | data: {safe_data}"

    log_msg += f" | user: {user_id}"

    log_func = getattr(logger, safe_level)
    log_func(log_msg)

    return {"status": "ok"}


@router.get("/api/user/wallet-status")
async def get_wallet_status(current_user: dict = Depends(get_current_user)):
    """獲取用戶錢包綁定狀態"""
    try:
        user_id = current_user["user_id"]
        if TEST_MODE and (
            user_id == TEST_USER.get("uid") or user_id.startswith("test-user-")
        ):
            return {
                "success": True,
                "has_wallet": True,
                "auth_method": "ton_wallet",
            }

        status = await run_sync(get_user_wallet_status, user_id)
        return {"success": True, **status}
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Get wallet status error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch status")


# --- User API Key Management Endpoints ---


class SaveAPIKeyRequest(BaseModel):
    provider: str
    api_key: str
    model: Optional[str] = None


class SaveModelRequest(BaseModel):
    provider: str
    model: str


@router.post("/api/user/api-keys")
@limiter.limit("10/minute")
async def save_user_api_key_endpoint(
    request: Request,
    req: SaveAPIKeyRequest,
    current_user: dict = Depends(get_current_user),
):
    """儲存用戶的 API Key（加密後存入資料庫）"""
    from core.orm.user_api_keys_repo import user_api_keys_repo

    user_id = current_user["user_id"]
    try:
        result = await user_api_keys_repo.save_user_api_key(
            user_id, req.provider, req.api_key, req.model
        )
        if not result["success"]:
            raise HTTPException(
                status_code=400, detail=result.get("error", "Failed to save API key")
            )

        logger.info(f"API key saved for user {user_id}, provider: {req.provider}")
        audit_log(
            action="api_key_saved",
            user_id=user_id,
            metadata={"provider": req.provider},
        )
        # BYOK 金鑰變動會改變 /api/user/tools 回應中的 key_status，需失效快取
        try:
            from api.routers.tools import invalidate_tools_cache

            invalidate_tools_cache(user_id=user_id)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.warning(f"[api-keys] Failed to invalidate tools cache: {e}")
        # 金鑰變動後，舊 session 的 ManagerAgent 仍持有用舊 key compile 的 graph，
        # 必須清掉該 user 所有 cached agents，下次對話才會用新 key 重建。
        try:
            from core.agents.bootstrap import invalidate_manager_cache

            invalidate_manager_cache(user_id)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.warning(f"[api-keys] Failed to invalidate manager cache: {e}")
        return {"success": True, "message": "API key saved securely"}

    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Save API key error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save")


@router.get("/api/user/api-keys")
async def get_user_api_keys_endpoint(
    kind: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """獲取用戶所有 API Key 的狀態（遮蔽版本，用於前端顯示）。

    可選 ``kind`` 查詢參數（"llm" | "tool"）僅回傳該類別的供應商。
    """
    from core.orm.user_api_keys_repo import user_api_keys_repo

    if kind is not None and kind not in ("llm", "tool"):
        raise HTTPException(status_code=400, detail="Invalid kind")

    user_id = current_user["user_id"]
    try:
        keys = await user_api_keys_repo.get_all_user_api_keys(user_id, kind=kind)
        return {"success": True, "keys": keys}
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Get API keys error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch")


@router.get("/api/user/tool-providers")
async def get_tool_providers_endpoint(current_user: dict = Depends(get_current_user)):
    """回傳所有 BYOK 工具供應商的前端顯示資訊（名稱、用途、申請連結）。"""
    from core.orm.user_api_keys_repo import tool_provider_meta

    return {"success": True, "providers": tool_provider_meta()}


@router.get("/api/user/api-keys/{provider}")
async def get_user_api_key_endpoint(
    provider: str, current_user: dict = Depends(get_current_user)
):
    """獲取特定 provider 的 API Key 狀態（遮蔽版本）"""
    from core.orm.user_api_keys_repo import user_api_keys_repo

    user_id = current_user["user_id"]
    try:
        key_info = await user_api_keys_repo.get_user_api_key_masked(user_id, provider)
        return {"success": True, **key_info}
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Get API key error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch")


@router.delete("/api/user/api-keys/{provider}")
@limiter.limit("10/minute")
async def delete_user_api_key_endpoint(
    request: Request,
    provider: str,
    model: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """刪除用戶的 API Key。

    帶 ``model`` 查詢參數時只刪該筆保存模型（刪到最後一個模型才連金鑰一併解綁）；
    不帶則整個 provider 解綁（金鑰＋全部保存模型）。
    """
    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", provider):
        raise HTTPException(status_code=400, detail="Invalid provider name")
    from core.orm.user_api_keys_repo import user_api_keys_repo

    user_id = current_user["user_id"]
    model_name = model.strip() if model else None
    try:
        if model_name:
            result = await user_api_keys_repo.delete_saved_model(
                user_id, provider, model_name
            )
        else:
            result = await user_api_keys_repo.delete_user_api_key(user_id, provider)
        if not result["success"]:
            raise HTTPException(
                status_code=400, detail=result.get("error", "Failed to delete")
            )

        logger.info(f"API key deleted for user {user_id}, provider: {provider}")
        metadata = {"provider": provider}
        if model_name:
            metadata["model"] = model_name
        audit_log(action="api_key_deleted", user_id=user_id, metadata=metadata)
        # BYOK 金鑰變動會改變 /api/user/tools 回應中的 key_status，需失效快取
        try:
            from api.routers.tools import invalidate_tools_cache

            invalidate_tools_cache(user_id=user_id)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.warning(f"[api-keys] Failed to invalidate tools cache: {e}")
        # 金鑰刪除後，舊 session 的 ManagerAgent 仍持有用舊 key compile 的 graph，
        # 必須清掉該 user 所有 cached agents，下次對話才會正確 fallback。
        try:
            from core.agents.bootstrap import invalidate_manager_cache

            invalidate_manager_cache(user_id)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.warning(f"[api-keys] Failed to invalidate manager cache: {e}")
        # 模型級刪除時把 provider_removed / active_model 回給前端，
        # 讓 UI 知道 provider 是否仍綁定、使用中的模型換成了誰
        extras = {k: v for k, v in result.items() if k != "success"}
        return {"success": True, "message": "API key deleted", **extras}

    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Delete API key error: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete")


class TestAPIKeyRequest(BaseModel):
    api_key: Optional[str] = None


@router.post("/api/user/api-keys/{provider}/test")
@limiter.limit("5/minute")
async def test_user_api_key_endpoint(
    request: Request,
    provider: str,
    req: Optional[TestAPIKeyRequest] = None,
    current_user: dict = Depends(get_current_user),
):
    """測試 BYOK 金鑰是否有效。body 不給 api_key 時讀使用者已儲存的金鑰。"""
    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", provider):
        raise HTTPException(status_code=400, detail="Invalid provider name")

    from core.orm.user_api_keys_repo import user_api_keys_repo
    from core.tools.key_tester import test_provider_key

    user_id = current_user["user_id"]
    api_key = req.api_key if req and req.api_key else None
    if not api_key:
        stored = await user_api_keys_repo.get_user_api_key(user_id, provider)
        if not stored:
            raise HTTPException(
                status_code=400, detail=f"No {provider} API key has been set. Unable to test."
            )
        api_key = stored

    # 測試呼叫是 sync requests，用 run_sync 包起來避免 block event loop
    from api.utils import run_sync

    result = await run_sync(test_provider_key, provider, api_key)
    audit_log(
        action="api_key_tested",
        user_id=user_id,
        metadata={
            "provider": provider,
            "success": result.get("success"),
            "status_code": result.get("status_code"),
        },
    )
    return result


_FEEDBACK_MSGS = {
    "success": {
        "zh-TW": "回饋已送出",
        "zh-CN": "反馈已提交",
        "en": "Feedback submitted successfully",
        "ru": "Отзыв успешно отправлен",
    },
    "empty": {
        "zh-TW": "回饋內容不可為空",
        "zh-CN": "反馈内容不能为空",
        "en": "Feedback message cannot be empty",
        "ru": "Сообщение не может быть пустым",
    },
    "failed": {
        "zh-TW": "送出失敗，請稍後再試",
        "zh-CN": "提交失败，请稍后再试",
        "en": "Failed to submit feedback",
        "ru": "Не удалось отправить отзыв",
    },
}


def _feedback_msg(key: str, language: str) -> str:
    lang = language if language in ("zh-TW", "zh-CN", "en", "ru") else "zh-TW"
    return _FEEDBACK_MSGS.get(key, {}).get(lang, key)


@router.post("/api/user-feedback")
@limiter.limit("10/minute")
async def submit_user_feedback(
    request: Request,
    body: UserFeedbackRequest,
    current_user: dict = Depends(get_current_user),
):
    """Receive platform feedback submitted from the settings page."""
    language = body.language
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail=_feedback_msg("empty", language))

    user_id = current_user["user_id"]
    username = current_user.get("username", "")

    try:
        existing_user = await run_sync(get_user_by_id, user_id)
        if not existing_user:
            fallback_auth_method = current_user.get("auth_method")
            if not fallback_auth_method:
                fallback_auth_method = (
                    "dev_test"
                    if TEST_MODE and str(user_id).startswith("test-user-")
                    else "ton_wallet"
                )
            await run_sync(
                create_or_get_user,
                user_id,
                username or None,
                fallback_auth_method,
            )
        await run_sync(save_user_feedback, user_id, username, message)
        audit_log(
            action="submit_user_feedback",
            user_id=user_id,
            metadata={"length": len(message)},
        )
        return {"success": True, "message": _feedback_msg("success", language)}
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Submit user feedback error: {e}")
        raise HTTPException(status_code=500, detail=_feedback_msg("failed", language))


@router.post("/api/user/api-keys/model")
@limiter.limit("10/minute")
async def save_user_model_endpoint(
    request: Request,
    req: SaveModelRequest,
    current_user: dict = Depends(get_current_user),
):
    """儲存用戶選擇的模型（不更改 API Key）"""
    from core.orm.user_api_keys_repo import user_api_keys_repo

    user_id = current_user["user_id"]
    try:
        result = await user_api_keys_repo.save_user_model_selection(
            user_id, req.provider, req.model
        )
        if not result["success"]:
            error_msg = result.get("error", "Failed to save model")
            if "No API key" in error_msg:
                return {"success": False, "message": error_msg}
            raise HTTPException(status_code=400, detail=error_msg)
        # 模型變動等同 LLM client 換新，舊 session 的 graph 也是用舊模型 compile，
        # 必須清掉 cached agents 確保下次對話用新模型。
        try:
            from core.agents.bootstrap import invalidate_manager_cache

            invalidate_manager_cache(user_id)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.warning(f"[api-keys] Failed to invalidate manager cache: {e}")
        return {"success": True, "message": "Model selection saved"}
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Save model error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save")


@router.get("/api/user/llm-debug")
async def llm_debug(
    request: Request,
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    """診斷 AI 深度分析所需的認證與 API Key 狀態。"""
    from api.user_llm import resolve_user_llm_credentials

    has_cookie = bool(request.cookies.get("access_token"))
    is_authed = bool(current_user and current_user.get("user_id"))
    user_id = current_user.get("user_id") if is_authed else None

    creds = (
        await resolve_user_llm_credentials(current_user, None) if is_authed else None
    )

    return {
        "has_cookie": has_cookie,
        "is_authenticated": is_authed,
        "user_id": user_id,
        "has_api_key": bool(creds),
        "provider": creds["provider"] if creds else None,
        "diagnosis": (
            "✅ Authentication and API key are OK; deep analysis should work"
            if creds
            else "❌ Not logged in. Please refresh the page or log in again"
            if not is_authed
            else "❌ Logged in but no API key found. Please re-save your key in Settings"
        ),
    }


_VALID_AGENT_IDS = frozenset({"crypto", "tw_stock", "us_stock", "chat"})


@router.get("/api/user/analysis-preferences")
async def get_analysis_preferences(
    current_user: dict = Depends(get_current_user),
):
    from core.database.preferences import get_all_preferences

    user_id = current_user["user_id"]
    try:
        prefs = await run_sync(get_all_preferences, user_id)
        return {
            "success": True,
            "preferences": [
                {
                    "agent_id": p.get("agent_id"),
                    "system_prompt": p.get("system_prompt"),
                    "enabled_tools": p.get("enabled_tools"),
                    "updated_at": p.get("updated_at"),
                }
                for p in prefs
            ],
        }
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Get analysis preferences error: {e}")
        raise HTTPException(status_code=500, detail="get failed")


@router.put("/api/user/analysis-preferences")
@limiter.limit("20/minute")
async def upsert_analysis_preference(
    request: Request,
    body: AnalysisPreferenceInput,
    current_user: dict = Depends(get_current_user),
):
    from core.database.preferences import upsert_preference
    from core.database.user import get_user_membership

    user_id = current_user["user_id"]
    membership = await run_sync(get_user_membership, user_id)
    if not membership.get("is_premium"):
        raise HTTPException(status_code=403, detail="Premium only")

    if body.agent_id not in _VALID_AGENT_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent_id. Must be one of: {', '.join(sorted(_VALID_AGENT_IDS))}",
        )

    if body.system_prompt and len(body.system_prompt) > 2000:
        raise HTTPException(status_code=400, detail="Too long")

    # 過濾 system prompt 的越權/jailbreak 模式(防禦深度,即使目前 system_prompt
    # 注入點尚未接線,預先設防)。Pydantic 層已擋 >2000 字,這裡擋惡意內容。
    from core.agents.prompt_guard import sanitize_system_prompt

    if body.system_prompt:
        body.system_prompt = sanitize_system_prompt(body.system_prompt)

    try:
        result = await run_sync(
            upsert_preference,
            user_id,
            body.agent_id,
            body.system_prompt,
            body.enabled_tools,
        )
        return {
            "success": True,
            "preference": {
                "agent_id": result.get("agent_id"),
                "system_prompt": result.get("system_prompt"),
                "enabled_tools": result.get("enabled_tools"),
                "updated_at": result.get("updated_at"),
            },
        }
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Upsert analysis preference error: {e}")
        raise HTTPException(status_code=500, detail="save failed")


@router.delete("/api/user/analysis-preferences/{agent_id}")
@limiter.limit("20/minute")
async def delete_analysis_preference(
    request: Request,
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    from core.database.preferences import delete_preference
    from core.database.user import get_user_membership

    user_id = current_user["user_id"]
    membership = await run_sync(get_user_membership, user_id)
    if not membership.get("is_premium"):
        raise HTTPException(status_code=403, detail="Premium only")

    if agent_id not in _VALID_AGENT_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent_id. Must be one of: {', '.join(sorted(_VALID_AGENT_IDS))}",
        )

    try:
        deleted = await run_sync(delete_preference, user_id, agent_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="not found")
        return {"success": True, "message": f"{agent_id} deleted"}
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Delete analysis preference error: {e}")
        raise HTTPException(status_code=500, detail="delete failed")


# ============================================================================






