# ruff: noqa: E402
# ^ E402 ignored because we need to modify sys.path before importing local modules
import asyncio
import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Fix Windows console encoding (cp950 cannot handle emoji/unicode)
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 將專案根目錄加入 Python 路徑
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Load environment variables
load_dotenv()

from config.logging_config import setup_json_logging

app_log_level_name = os.getenv("APP_LOG_LEVEL", "WARNING").upper()
app_log_level = getattr(logging, app_log_level_name, logging.WARNING)

use_json_logging = os.getenv("LOG_FORMAT", "text").lower() == "json"

if use_json_logging:
    setup_json_logging(app_log_level)
else:
    log_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(app_log_level)
    console_handler.setFormatter(log_formatter)
    logging.basicConfig(
        level=app_log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[console_handler],
    )


# 靜音 Windows asyncio WinError 10054（客戶端斷線時的無害噪音）
class _SuppressWinError10054(logging.Filter):
    def filter(self, record):
        return "WinError 10054" not in (record.getMessage())


logging.getLogger("asyncio").addFilter(_SuppressWinError10054())

# Import from refactored modules
from api.deps import get_current_user, require_admin
from api.health import router as health_router
from api.lifespan import lifespan
from api.middleware_setup import setup_middleware
from api.routers import (
    analysis,
    astock,
    commodity,
    forex,
    guest,
    hkstock,
    instock,
    jpstock,
    krstock,
    market,
    system,
    twstock,
    user,
    usstock,
)
from api.routers.admin import router as admin_router
from api.routers.agent_presets import (
    router as agent_presets_router,  # Agent presets API
)
from api.routers.alerts import router as alerts_router  # Price Alerts API
from api.routers.audit import router as audit_router  # Audit log admin API
from api.routers.audit import (
    user_router as audit_user_router,  # 使用者視角 audit（信任層）
)
from api.routers.discover import router as discover_router  # Discover API
from api.routers.forum import router as forum_router
from api.routers.friends import router as friends_router
from api.routers.frontend_errors import (
    router as frontend_errors_router,  # Frontend Error Boundary
)
from api.routers.governance import (
    router as governance_router,  # Community governance API
)
from api.routers.guard_management import router as guard_management_router
from api.routers.guard_v1 import router as guard_v1_router
from api.routers.journal import (
    router as journal_router,  # 統一帳本  # Memory management API
)
from api.routers.memory import router as memory_router
from api.routers.messages import router as messages_router
from api.routers.notifications import (
    router as notifications_router,  # Notifications API
)
from api.routers.premium import router as premium_router
from api.routers.scam_tracker import router as scam_tracker_router  # Scam tracker API
from api.routers.skills import router as skills_router  # Skill management API
from api.routers.studio import (
    router as studio_router,  # 提案工作台 API（design 2026-08-16，flag 控制）
)
from api.routers.telegram_link import (
    router as telegram_router,  # Telegram Bot binding + chat
)
from api.routers.tools import router as tools_router  # Tool preferences API
from api.routers.trust import router as trust_router  # Trust score (self/badge)
from api.routers.wallet_monitor import (
    router as wallet_monitor_router,  # Wallet monitor dashboard
)
from api.utils import logger

# ================================================================
# PRODUCTION SAFETY GUARD — refuse to start if TEST_MODE is
# enabled in a production environment (no auth bypass allowed)
# ================================================================
_env = os.getenv("ENVIRONMENT", "development").lower()
_test_mode = os.getenv("TEST_MODE", "false").lower()
if _env == "production" and _test_mode == "true":
    raise RuntimeError(
        "FATAL: TEST_MODE=true is set but ENVIRONMENT=production. "
        "This bypasses authentication and is not allowed in production. "
        "Set TEST_MODE=false or ENVIRONMENT=development to proceed."
    )
del _env, _test_mode
# ================================================================
# PRODUCTION SAFETY GUARD — API Key encryption key must be properly configured
# ================================================================
_env = os.getenv("ENVIRONMENT", "development").lower()
if _env == "production":
    secret = os.getenv("API_KEY_ENCRYPTION_SECRET")
    if not secret or len(secret) < 32:
        raise RuntimeError(
            "FATAL: API_KEY_ENCRYPTION_SECRET is not properly configured. "
            "In production, this environment variable must be set with a "
            "secret of at least 32 characters to decrypt stored user API keys. "
            "See README.md for setup instructions."
        )
del _env
# ================================================================

# --- 創建 FastAPI 應用 ---
app = FastAPI(title="Crypto Trading System API", version="1.2.0", lifespan=lifespan)

# --- 註冊 Middleware ---
setup_middleware(app)

# ================================================================
# Include API Routers
# ================================================================
# Safety/Guard 叢集：2026-08-13 決策關閉（governance／guard 兩個 router）。
# scam-tracker API 於 2026-08-18 拆出重啟——地址健診 v0（DANNY 核准）依賴它；
# 如需回滾整個 API：env SCAM_TRACKER_API_ENABLED=0。
SCAM_TRACKER_API_ENABLED = os.getenv("SCAM_TRACKER_API_ENABLED", "1").lower() in (
    "1",
    "true",
    "yes",
)
SAFETY_FEATURE_ENABLED = False

app.include_router(frontend_errors_router)  # Frontend Error Boundary
app.include_router(system.router)
app.include_router(analysis.router)
app.include_router(guest.router)  # 訪客模式（免登入 AI 分析）
app.include_router(market.router)
app.include_router(twstock.router)
app.include_router(usstock.router)
app.include_router(commodity.router)
app.include_router(forex.router)
app.include_router(hkstock.router)  # 港股 API
app.include_router(astock.router)  # A 股 API
app.include_router(jpstock.router)  # 日股 API
app.include_router(instock.router)  # 印度股 API
app.include_router(krstock.router)  # 韓股 API
app.include_router(user.router)
app.include_router(health_router)  # Health check endpoints
app.include_router(forum_router)  # 論壇 API
app.include_router(premium_router)  # 高級會員 API
app.include_router(admin_router)  # 管理員/後台 API
app.include_router(friends_router)  # 好友功能 API
app.include_router(messages_router)  # 私訊功能 API
app.include_router(audit_router)  # 審計日誌查詢 API (管理員專用)
app.include_router(audit_user_router)  # 使用者視角信任層稽核 API
app.include_router(trust_router)  # Trust score（自己看明細 / 別人看徽章）
app.include_router(wallet_monitor_router)  # 錢包監測 dashboard（警示設定）
if SCAM_TRACKER_API_ENABLED:
    app.include_router(scam_tracker_router)  # 可疑錢包追蹤＋地址健診（2026-08-18 重啟）
if SAFETY_FEATURE_ENABLED:
    app.include_router(governance_router)  # 社群治理系統 API
    app.include_router(guard_management_router)  # Guard owner/client/policy management
    app.include_router(guard_v1_router)  # External Agent Guard decision API
app.include_router(notifications_router)  # 通知系統 API
app.include_router(alerts_router)  # 價格警報 API
app.include_router(memory_router)
app.include_router(journal_router)  # 統一帳本  # 記憶管理 API
app.include_router(skills_router)  # Skill 管理 API
app.include_router(tools_router)  # 工具偏好 API
app.include_router(agent_presets_router)  # Agent Profile/Preset API（Phase 2，flag 控制）
app.include_router(discover_router)  # People & Projects 探索 API（Phase 3，flag 控制）
app.include_router(studio_router)  # 提案工作台（募資者模式，flag 控制）
app.include_router(telegram_router)  # Telegram Bot 綁定 + 聊天


# --- Public base-URL resolution (shared by all site-level manifests) ---
from urllib.parse import urlparse, urlunparse

from core.config import TON_MANIFEST_URL

_IS_PRODUCTION = os.getenv("ENVIRONMENT", "development").lower() in {
    "production",
    "prod",
}


def _resolve_public_base(request: Request) -> str:
    """
    回傳對外的站台 base URL（不含尾斜線），給站點層級 manifest 用。

    Zeabur（與任何 TLS-terminating proxy）用純 HTTP 連進容器，而 gunicorn 的
    forwarded_allow_ips 預設只信 127.0.0.1 → request.base_url 拿到的是
    "http://..."。manifest 發出 http 但站台是 https 時，錢包掃完 QR / PWA
    安裝都會壞掉（9377ffd 踩過的線上登入斷線）。所以 scheme 一律以
    X-Forwarded-Proto 第一跳為準；production 缺標頭時保底 https。

    TON_MANIFEST_URL env 只當對照（不符時 log warning），實際採用請求來源
    的 host（更可靠：Zeabur 改網域時不靠手動同步 env）。
    """
    request_base = str(request.base_url).rstrip("/")
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    forwarded_proto = forwarded_proto.split(",")[0].strip().lower()
    if forwarded_proto not in ("http", "https") and _IS_PRODUCTION:
        # 保底：production 一律走 HTTPS。就算某層 proxy 沒帶 X-Forwarded-Proto，
        # 也絕不能發出 http 的 manifest 把登入/安裝弄掛。
        forwarded_proto = "https"
    if forwarded_proto in ("http", "https"):
        request_base = urlunparse(
            urlparse(request_base)._replace(scheme=forwarded_proto)
        ).rstrip("/")
    env_base = TON_MANIFEST_URL.rstrip("/")
    if env_base and env_base != request_base:
        logger.warning(
            "[manifest] TON_MANIFEST_URL (%s) != request host (%s); using request host",
            env_base,
            request_base,
        )
    return request_base or env_base


# --- TON Connect manifest ---
@app.get("/tonconnect-manifest.json")
async def tonconnect_manifest(request: Request):
    """
    Manifest consumed by TON Connect wallets when a user connects.
    Must be reachable at a public HTTPS URL (TON_MANIFEST_URL).

    termsOfUseUrl / privacyPolicyUrl are optional for basic listing but
    required for the Tonkeeper recommended-apps list, and ton.app review
    treats them as strong quality signals. Both documents are served as
    static files from web/legal/ at the /legal/ mount.
    """
    base = _resolve_public_base(request)
    return {
        "url": base,
        "name": "CryptoMind",
        "iconUrl": f"{base}/static/img/title_icon.png",
        "termsOfUseUrl": f"{base}/legal/terms-of-service.html",
        "privacyPolicyUrl": f"{base}/legal/privacy-policy.html",
    }


# --- PWA web app manifest (installability) ---
@app.get(
    "/manifest.webmanifest",
    response_class=JSONResponse,
)
async def pwa_manifest(request: Request):
    """
    Web app manifest — 讓 CryptoMind 可被「安裝」（iOS 加到主畫面 / Android
    安裝提示 / 桌面 PWA）。第一階段只做可安裝，不含 service worker（即時
    行情 + agent 對話的快取策略需另案設計，避免拿到舊報價/session）。

    MIME 必須是 application/manifest+json（X-Content-Type-Options: nosniff
    已開，錯的 MIME 會被瀏覽器拒收）。base URL 重用 _resolve_public_base，
    與 tonconnect 共用同一條 Zeabur proxy scheme 修復邏輯。
    """
    base = _resolve_public_base(request)
    icons = [
        {
            "src": f"{base}/static/img/icon-192.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": f"{base}/static/img/icon-512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": f"{base}/static/img/icon-192-maskable.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "maskable",
        },
        {
            "src": f"{base}/static/img/icon-512-maskable.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ]
    # JSONResponse 顯式指定 manifest MIME，覆寫預設 application/json。
    manifest = {
        "name": "CryptoMind",
        "short_name": "CryptoMind",
        "description": "AI 驅動的加密貨幣與股票分析平台",
        "start_url": f"{base}/",
        "scope": f"{base}/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0b0b12",
        "theme_color": "#0b0b12",
        "lang": "zh-TW",
        "dir": "ltr",
        "categories": ["finance", "productivity"],
        "icons": icons,
    }
    return JSONResponse(
        content=manifest, media_type="application/manifest+json"
    )


@app.get("/favicon.ico")
async def favicon():
    """重導到實體 PNG。/favicon.ico 一直被敲 404（audit log 早已列為 skip）。"""
    return RedirectResponse(url="/static/img/title_icon.png")


# --- Service worker ---
# vite-plugin-pwa 因 base:'/static/' 把 sw.js 產到 /static/sw.js，預設 scope 只到
# /static/。要控制全站 /（含根路徑 index.html），SW 必須在 /sw.js 服務並送
# Service-Worker-Allowed: / header，前端才能 register('/sw.js', { scope:'/' })。
#
# 路徑解析順序（涵蓋本機 dev 與 runtime image 兩種佈局）：
#   1. SW_JS_PATH env（覆寫用）
#   2. web/sw.js       ← runtime image：Dockerfile 把 build 產出 overlay 到 web/
#   3. dist/static/sw.js ← 本機 npm run build 後
#   4. web/public/sw.js  ← 本機 vite dev / 未 build
_SW_JS_CANDIDATES = [
    os.getenv("SW_JS_PATH"),
    "web/sw.js",
    "dist/static/sw.js",
    "web/public/sw.js",
]


def _resolve_sw_js_path():
    for p in _SW_JS_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def _resolve_workbox_path(filename: str):
    """Resolve workbox-<hash>.js bundled next to sw.js.

    generateSW 產出的 sw.js 用相對路徑 ``./workbox-<hash>`` 引用此檔；
    因為 sw.js 在根路徑 / 服務，瀏覽器會請求 ``GET /workbox-<hash>.js``，
    必須在根路徑提供此檔，否則 SW 載入失敗。尋找邏輯與 sw.js 同一組目錄。
    """
    import glob as _glob

    # 候選目錄：與 _SW_JS_CANDIDATES 對齊（去 None、取目錄）
    search_dirs = []
    for cand in _SW_JS_CANDIDATES:
        if cand:
            search_dirs.append(os.path.dirname(cand) or ".")
    for d in dict.fromkeys(search_dirs):  # 去重並保留順序
        # 精確檔名匹配（避免 glob 到非預期檔案）
        exact = os.path.join(d, filename)
        if os.path.isfile(exact):
            return exact
    # 退一步：目錄內唯一 workbox-*.js（寬容匹配）
    for d in dict.fromkeys(search_dirs):
        hits = _glob.glob(os.path.join(d, "workbox-*.js"))
        if hits:
            return hits[0]
    return None


@app.get("/workbox-{rest}.js")
async def workbox_runtime(rest: str):
    """服務 generateSW 附帶的 workbox-<hash>.js。

    sw.js 以相對路徑 ``./workbox-<hash>`` 引用本檔；因為 sw.js 在根路徑 / 服務，
    瀏覽器解析成 ``GET /workbox-<hash>.js``，必須在根路徑提供，否則 SW 整個載入失敗。
    檔案不存在（未 build）時回 404，前端註冊腳本會 try/catch 忽略。
    """
    path = _resolve_workbox_path(f"workbox-{rest}.js")
    if path is None:
        return PlainTextResponse(
            "// workbox bundle not built", status_code=404, media_type="text/javascript"
        )
    with open(path, "r", encoding="utf-8") as f:
        body = f.read()
    return PlainTextResponse(
        body,
        media_type="text/javascript",
        # 與 /static 資源一致：每次重驗，確保 SW 更新流程拿得到新版。
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/sw.js")
async def service_worker():
    """服務 service worker 並送 scope 擴展 header。

    檔案不存在（未 build）時回 404，前端註冊腳本會 try/catch 忽略。
    """
    path = _resolve_sw_js_path()
    if path is None:
        return PlainTextResponse(
            "// service worker not built", status_code=404, media_type="text/javascript"
        )
    with open(path, "r", encoding="utf-8") as f:
        body = f.read()
    # Cache-Control: no-cache（每次重驗，確保 SW 更新檢查拿得到新版）。
    # 不能 no-store（會破壞 Workbox 的更新流程）。
    return PlainTextResponse(
        body,
        media_type="text/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )


# --- SEO: robots.txt + sitemap.xml ---
# 本站是登入後才有內容的 SPA，主要通路是 Telegram/TON 生態，不是 Google。
# 這兩個檔案只為「品牌搜尋乾淨呈現 + 連結分享」服務，不放 /api/ 給爬蟲。
@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    base = TON_MANIFEST_URL.rstrip("/")
    return f"User-agent: *\nDisallow: /api/\nAllow: /\n\nSitemap: {base}/sitemap.xml\n"


@app.get("/sitemap.xml")
async def sitemap_xml():
    from fastapi.responses import Response

    base = TON_MANIFEST_URL.rstrip("/")
    paths = (
        ("/", "weekly", "1.0"),
        ("/legal/terms-of-service.html", "yearly", "0.3"),
        ("/legal/privacy-policy.html", "yearly", "0.3"),
        ("/legal/community-guidelines.html", "yearly", "0.3"),
    )
    urls = "".join(
        f"<url><loc>{base}{p}</loc>"
        f"<changefreq>{cf}</changefreq>"
        f"<priority>{pr}</priority></url>"
        for p, cf, pr in paths
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )
    return Response(content=body, media_type="application/xml")


# --- llms.txt（AI 友善文件，llmstxt.org 標準）---
# 讓 AI 搜尋/agent 精準理解平台：定位、功能、登入、合規邊界。
# 內容與時俱進（功能變更時更新），維持簡短（<3KB 最佳）。
@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt():
    return (
        "# CryptoMind — AI-Powered Crypto & Stock Analysis Platform\n\n"
        "## About\n"
        "CryptoMind is an AI-driven financial analysis platform covering "
        "cryptocurrencies (BTC/ETH/SOL/TON), Taiwan stocks, US stocks, and "
        "global markets (HK/JP/KR/IN). It provides conversational AI analysis, "
        "real-time market data, technical indicators, TON wallet asset overview, "
        "scam detection, and multi-chain wallet monitoring.\n\n"
        "## Platform Positioning & Compliance\n"
        "- Non-custodial: users connect their own TON wallet (Tonkeeper) via "
        "TON Connect. The platform never holds private keys, never manages "
        "user assets, and does NOT provide token swap/exchange services.\n"
        "- Bring-Your-Own-Key (BYOK): users bring their own LLM API key "
        "(OpenRouter/DeepSeek/OpenAI/etc.) for AI analysis.\n"
        "- Free tier: 5 AI chat messages per day. Premium: unlimited (USD-anchored "
        "pricing, paid in TON).\n\n"
        "## Links\n"
        "- [CryptoMind Home](https://cryptomind-ton.zeabur.app/): the SPA app "
        "(login required for most features; TON Connect for wallet auth)\n"
        "- [Terms of Service](https://cryptomind-ton.zeabur.app/legal/terms-of-service.html): "
        "platform terms\n"
        "- [Privacy Policy](https://cryptomind-ton.zeabur.app/legal/privacy-policy.html): "
        "data handling\n"
        "- [Community Guidelines](https://cryptomind-ton.zeabur.app/legal/community-guidelines.html): "
        "posting rules\n\n"
        "## API Notes\n"
        "- API endpoints under /api/ require authentication (JWT cookie from "
        "TON Connect login).\n"
        "- Admin endpoints under /api/admin/ are restricted to admin role.\n"
        "- No public unauthenticated data API is exposed for scraping.\n"
    )


# --- 前端 Debug Log API ---
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

from pydantic import BaseModel, Field

_frontend_logger = logging.getLogger("frontend_debug")
_frontend_logger.setLevel(logging.INFO)
if not _frontend_logger.handlers:
    _rotating_handler = RotatingFileHandler(
        "frontend_debug.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    _rotating_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    _frontend_logger.addHandler(_rotating_handler)


_VALID_LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical"})


class FrontendLog(BaseModel):
    level: str = "info"
    message: str = Field(max_length=2000)
    data: Optional[dict] = None


@app.post("/api/debug-log")
async def receive_frontend_log(
    log: FrontendLog, current_user: dict = Depends(get_current_user)
):
    """接收前端 debug log 並寫入檔案 (需登入)"""
    safe_level = log.level.lower() if log.level.lower() in _VALID_LOG_LEVELS else "info"
    log_func = getattr(_frontend_logger, safe_level)
    safe_message = log.message.replace("\n", " ").replace("\r", " ")
    log_line = safe_message
    if log.data:
        safe_data = str(log.data).replace("\n", " ").replace("\r", " ")
        log_line += f" | Data: {safe_data}"
    log_func(log_line)
    return {"status": "logged"}


@app.get("/api/debug-log", response_class=PlainTextResponse)
async def get_debug_logs(admin: dict = Depends(require_admin)):
    """查看 debug logs (需管理員權限) — 僅讀取最後 100KB"""
    try:

        def _read_log():
            import os

            size = os.path.getsize("frontend_debug.log")
            with open("frontend_debug.log", "r", encoding="utf-8") as f:
                if size > 100 * 1024:
                    f.seek(max(0, size - 100 * 1024))
                    return "... (truncated) ...\n" + f.read()
                return f.read()

        return await asyncio.get_running_loop().run_in_executor(None, _read_log)
    except FileNotFoundError:
        return "No logs yet"


# Note: Duplicate root validation-key route removed; now handled by pi_validation.


# --- 靜態檔案與頁面 ---
if os.path.exists("web"):
    app.mount("/static", StaticFiles(directory="web"), name="static")
    for sub in ("js", "css", "img", "assets", "scam-tracker", "legal"):
        sub_dir = os.path.join("web", sub)
        if os.path.isdir(sub_dir):
            # html=True：目錄根路徑解析 index.html（/scam-tracker/ 直達頁面）
            # 且關閉目錄瀏覽（比預設更安全）
            app.mount(f"/{sub}", StaticFiles(directory=sub_dir, html=True), name=sub)
    logger.info("Static files mounted (no-cache via security middleware)")

if __name__ == "__main__":
    logger.info("🚀 Pi Crypto Insight API Server 啟動中...")
    logger.info("VERIFICATION_TAG: Fix-500-Masking-v3-Robust")
    logger.info("🏠 本地網址: http://localhost:8080")
    logger.info("📱 請使用 HTTPS 網址訪問 (如透過 ngrok)")
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))

    # Uvicorn requires an import string when using multiple workers or reload.
    if workers > 1:
        logger.info(
            f"👷 Using WEB_CONCURRENCY={workers}, starting with import string mode"
        )
        uvicorn.run("api_server:app", host="0.0.0.0", port=8080, workers=workers)
    else:
        uvicorn.run(app, host="0.0.0.0", port=8080)
