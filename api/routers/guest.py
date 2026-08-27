"""訪客模式 API — 免登入體驗 AI 市場分析（設計：docs/plans/2026-08-19-guest-access-design.md）。

邊界（與主 /api/analyze 完全分離，主流程零風險）：
- 訪客身分：簽名 cookie ``guest_id``（uuid + HMAC），30 天，不建 user 列（零 schema）
- 每日限量：``GUEST_DAILY_QUESTIONS``（預設 3/天，UTC 日），Redis shared_cache 計數
- 全站每日總量：``GUEST_GLOBAL_DAILY_CAP``（預設 300/天，0=關）— 防「清 cookie 換新
  身分」輪替打爆平台 OpenRouter 免費線日額（DANNY 2026-08-20 決策）
- 模型：平台金鑰（env ``GUEST_LLM_PROVIDER``/``GUEST_LLM_MODEL``，預設 openrouter 免費模型）
- 高風險功能一律不開放：本 router 只有聊天，其餘路由照舊 get_current_user fail-closed
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.middleware.rate_limit import limiter
from api.utils import logger
from core import shared_cache
from core.config import TEST_MODE
from core.validators.content_filter import filter_chat_message
from utils.llm_client import LLMClientFactory

router = APIRouter()

GUEST_COOKIE = "guest_id"
_GUEST_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 天
_DEFAULT_DAILY = 3
# 全站訪客每日總量上限（與每人限量同一套 Redis/local 計數模式）。
# 用意：每人限量靠 cookie 可被「清 cookie 換身分」繞過，全站計數才是
# 保護平台 OpenRouter 免費日額的硬上限；0 = 關閉（僅留每人限量）。
_DEFAULT_GLOBAL_DAILY = 300
# 訪客模型預設走 openrouter 免費線（env GUEST_LLM_MODEL 可覆蓋）。
# 2026-08-19：deepseek-r1:free 已退場（OpenRouter 404 "unavailable for
# free"），改用平台實際在用的 nemotron 免費席次。
_DEFAULT_PROVIDER = "openrouter"
_DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

# 匿名化：log 只留 guest_id 前 8 碼
_GUEST_LOG_PREFIX_LEN = 8


def _guest_secret() -> str:
    """訪客 cookie 簽名金鑰 — 與 JWT 同源（api.deps 同款讀法）。"""
    from api.deps import SECRET_KEY

    return SECRET_KEY


def _sign(value: str) -> str:
    return hmac.new(
        _guest_secret().encode(), value.encode(), hashlib.sha256
    ).hexdigest()[:16]


def _issue_guest_id() -> str:
    raw = uuid.uuid4().hex
    return f"{raw}.{_sign(raw)}"


def _valid_guest_id(value: str) -> bool:
    if not value or "." not in value:
        return False
    raw, _, sig = value.rpartition(".")
    return bool(re.fullmatch(r"[0-9a-f]{32}", raw)) and hmac.compare_digest(
        _sign(raw), sig
    )


def _resolve_guest(request: Request, response: Response) -> str:
    """讀取或發放訪客 id（簽名 cookie）。無效簽名一律換新（不信任舊值）。"""
    value = request.cookies.get(GUEST_COOKIE, "")
    if not _valid_guest_id(value):
        value = _issue_guest_id()
        response.set_cookie(
            GUEST_COOKIE,
            value,
            max_age=_GUEST_COOKIE_MAX_AGE,
            httponly=True,
            secure=not TEST_MODE,
            samesite="lax",
            path="/",
        )
    return value


def _daily_limit() -> int:
    raw = os.getenv("GUEST_DAILY_QUESTIONS", "").strip()
    try:
        n = int(raw) if raw else _DEFAULT_DAILY
    except ValueError:
        n = _DEFAULT_DAILY
    return max(0, n)


def _global_cap() -> int:
    raw = os.getenv("GUEST_GLOBAL_DAILY_CAP", "").strip()
    try:
        n = int(raw) if raw else _DEFAULT_GLOBAL_DAILY
    except ValueError:
        n = _DEFAULT_GLOBAL_DAILY
    return max(0, n)


# 模型鏈：主模型（GUEST_LLM_MODEL，預設 nemotron 免費線）＋備用
# （GUEST_LLM_FALLBACK_MODELS，逗號分隔）。免費線日額（帳號級）耗盡或
# 模型退場時自動切備用——訪客模式是行銷入口，不該因單一模型掛掉而整個 502。
def _model_chain() -> list[str]:
    primary = (os.getenv("GUEST_LLM_MODEL") or _DEFAULT_MODEL).strip()
    raw = os.getenv("GUEST_LLM_FALLBACK_MODELS", "").strip()
    chain = [primary] + [m.strip() for m in raw.split(",") if m.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


# 視為「模型額度/可用性」問題的錯誤特徵——這類才值得燒備用鏈重試；
# 其他（網路瞬斷、輸出壞掉）重試別的模型也沒意義，直接上拋。
_QUOTA_ERROR_MARKERS = ("429", "404", "rate limit", "unavailable", "not found", "quota")


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _QUOTA_ERROR_MARKERS)


def _quota_key(guest_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    raw = guest_id.rpartition(".")[0]
    return f"guest_quota:{raw}:{day}"


def _global_key() -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"guest_quota:global:{day}"


# 進程內 fallback：shared_cache 無 Redis 時是靜默 no-op（get 永遠 None），
# 配額會形同虛設。這裡用本地 dict 兜底 —— 生產多 worker 下 Redis 命中（正確），
# 單機/測試/Redis 故障時至少單進程內限量仍成立（fail-safe 而非 fail-open）。
_local_quota: dict[str, int] = {}


def _quota_used(guest_id: str) -> int:
    key = _quota_key(guest_id)
    remote = shared_cache.get_json(key)
    if remote is not None:
        return int(remote)
    return _local_quota.get(key, 0)


def _quota_remaining(guest_id: str) -> int:
    """剩餘次數 = 限額 − 已用。計數有輕微 race 可容忍（免費額度用途）。"""
    return max(0, _daily_limit() - _quota_used(guest_id))


def _consume_quota(guest_id: str) -> int:
    key = _quota_key(guest_id)
    used = _quota_used(guest_id) + 1
    shared_cache.set_json(key, used, ttl=2 * 86400)
    if shared_cache.get_json(key) is None:  # Redis 沒寫入（不可用）→ 本地兜底
        _local_quota[key] = used
    _global_bump()  # 成功回覆才計全站（LLM 失敗不燒平台日額預算）
    return max(0, _daily_limit() - used)


_local_global: dict[str, int] = {}


def _global_used() -> int:
    key = _global_key()
    remote = shared_cache.get_json(key)
    if remote is not None:
        return int(remote)
    return _local_global.get(key, 0)


def _global_bump() -> None:
    key = _global_key()
    used = _global_used() + 1
    shared_cache.set_json(key, used, ttl=2 * 86400)
    if shared_cache.get_json(key) is None:
        _local_global[key] = used


def _market_snapshot() -> str:
    """即時行情快照（BTC/ETH/TON 現價 + 24h 漲跌），失敗回空字串（fail-open）。"""
    from data.market_data import get_klines  # noqa: PLC0415

    lines = []
    for sym in ("BTC", "ETH", "TON"):
        try:
            df = get_klines(f"{sym}USDT", exchange="okx", interval="1d", limit=2)
            if df is None or len(df) < 1:
                continue
            last = float(df["close"].iloc[-1])
            prev = float(df["close"].iloc[-2]) if len(df) >= 2 else last
            chg = ((last - prev) / prev * 100) if prev else 0.0
            lines.append(f"- {sym}: ${last:,.2f} ({chg:+.2f}% 24h)")
        except Exception as exc:  # 單一幣失敗不擋其他
            logger.warning("[Guest] snapshot %s failed: %s", sym, exc)
    return "\n".join(lines)


_GUEST_SYSTEM_PROMPT = """You are CryptoMind's market analyst giving a free guest demo answer.

Rules:
1. Answer the user's market question directly and concisely (under 250 words), in {language}.
2. You may use the live data below if relevant; do NOT invent prices.
3. You cannot run tools, charts, or wallet checks in guest mode — if asked, explain briefly \
that connecting a TON wallet unlocks the full agent (live charts, multi-agent deep analysis, \
risk-gated swaps, address checkup).
4. Bookkeeping/ledger requests (e.g. "記一筆 300", "record lunch 250"): the ledger \
requires a logged-in account. Do NOT claim anything was recorded or a proposal was \
sent — tell the user to connect their TON wallet / log in to record expenses, income \
and trades. (2026-08-23: guest 幻覺「已記錄」修正)
5. End with one line: "Not financial advice."

Live data (may be empty):
{snapshot}"""


class GuestAnalyzeRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language: Optional[str] = Field(default=None, max_length=10)


class GuestAnalyzeResponse(BaseModel):
    reply: str
    remaining: int
    limit: int


class GuestQuotaResponse(BaseModel):
    limit: int
    remaining: int


@router.get("/api/guest/quota")
@limiter.limit("30/minute")
async def guest_quota(request: Request, response: Response) -> GuestQuotaResponse:
    """訪客額度查詢（guest banner 顯示每日限額用）：不扣額度、不碰 LLM。"""
    guest_id = _resolve_guest(request, response)
    return GuestQuotaResponse(
        limit=_daily_limit(), remaining=_quota_remaining(guest_id)
    )


@router.post("/api/guest/analyze")
@limiter.limit("5/minute")
async def guest_analyze(
    request: Request, response: Response, body: GuestAnalyzeRequest
) -> GuestAnalyzeResponse:
    """訪客 AI 市場分析（免登入、每日限量、平台免費模型）。"""
    guest_id = _resolve_guest(request, response)
    short_id = guest_id[:_GUEST_LOG_PREFIX_LEN]

    # 輸入防護：與主聊天同一套 content filter
    filter_result = filter_chat_message(body.message)
    if not filter_result["valid"]:
        raise HTTPException(
            status_code=400, detail="Message could not be processed."
        )

    if _quota_remaining(guest_id) <= 0:
        raise HTTPException(
            status_code=429,
            detail=(
                "Guest daily limit reached. "
                "Connect a TON wallet for unlimited AI analysis."
            ),
        )

    if _global_cap() and _global_used() >= _global_cap():
        # 個人額度可能還有，但全站日額用罄（防輪替身分打爆平台免費線）
        logger.warning("[Guest] global daily cap hit (%d)", _global_cap())
        raise HTTPException(
            status_code=429,
            detail=(
                "Guest mode is at full capacity today. "
                "Connect a TON wallet or come back tomorrow."
            ),
        )

    provider = (os.getenv("GUEST_LLM_PROVIDER") or _DEFAULT_PROVIDER).strip()

    # 即時快照在配額扣用前抓（抓不到照樣可答，fail-open）
    snapshot = await _safe_snapshot()

    from langchain_core.messages import HumanMessage, SystemMessage  # noqa: PLC0415

    language = (body.language or "zh-TW").strip()
    lang_name = {"en": "English", "ru": "Русский", "zh-CN": "简体中文"}.get(
        language, "繁體中文"
    )
    messages = [
        SystemMessage(
            content=_GUEST_SYSTEM_PROMPT.format(
                language=lang_name, snapshot=snapshot
            )
        ),
        HumanMessage(content=body.message),
    ]

    try:
        result, used_model = await _invoke_with_model_fallback(
            provider, messages, short_id
        )
    except TimeoutError:
        logger.warning("[Guest] LLM timeout guest=%s", short_id)
        raise HTTPException(status_code=504, detail="Analysis timed out, please retry.")
    except ValueError as exc:
        # 模型鏈全部因平台金鑰缺失而無法建立 client → 訪客模式優雅關閉
        logger.warning("[Guest] platform LLM key unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Guest mode is temporarily unavailable. "
                "Connect a TON wallet to use your own API key."
            ),
        ) from exc
    except Exception as exc:
        logger.error("[Guest] LLM failed guest=%s: %s", short_id, exc)
        raise HTTPException(status_code=502, detail="Analysis failed, please retry.")

    text = str(getattr(result, "content", "") or "").strip() or "(empty response)"
    remaining = _consume_quota(guest_id)
    logger.info(
        "[Guest] answered guest=%s model=%s remaining=%d/%d",
        short_id, used_model, remaining, _daily_limit(),
    )
    return GuestAnalyzeResponse(
        reply=text, remaining=remaining, limit=_daily_limit()
    )


async def _safe_snapshot() -> str:
    """同步行情抓取丟 thread pool（不在 event loop 做 sync I/O），3 秒逾時 fail-open。"""
    import asyncio  # noqa: PLC0415

    try:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(None, _market_snapshot),
            timeout=3.0,
        )
    except (asyncio.CancelledError, TimeoutError):
        return ""
    except Exception as exc:
        logger.warning("[Guest] snapshot wrapper failed: %s", exc)
        return ""


async def _invoke_with_timeout(client, messages):
    import asyncio  # noqa: PLC0415

    loop = asyncio.get_running_loop()

    def _call():
        return client.invoke(messages, max_tokens=1200)

    return await asyncio.wait_for(
        loop.run_in_executor(None, _call), timeout=90.0
    )


async def _invoke_with_model_fallback(provider: str, messages, guest_id_short: str):
    """沿模型鏈重試：額度/可用性錯誤（429/404/...）換下一個模型。

    回傳 (result, model)。全部模型都不可用時拋出最後一個例外——
    呼叫端維持原本的 502 語意。平台金鑰完全缺失（ValueError）也逐模型
    嘗試後上拋，由呼叫端轉 503。
    """
    chain = _model_chain()
    last_exc: Exception | None = None
    for model in chain:
        try:
            client = LLMClientFactory.create_client(provider=provider, model=model)
        except ValueError as exc:
            last_exc = exc
            logger.warning("[Guest] client init failed model=%s: %s", model, exc)
            continue
        try:
            result = await _invoke_with_timeout(client, messages)
            return result, model
        except Exception as exc:
            last_exc = exc
            if not _is_quota_error(exc):
                raise
            logger.warning(
                "[Guest] model %s quota/unavailable, trying next (guest=%s): %s",
                model, guest_id_short, exc,
            )
    assert last_exc is not None
    raise last_exc
