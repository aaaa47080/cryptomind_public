FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# --- Python dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
    && pip wheel --wheel-dir /wheels -r requirements.txt

# --- Frontend dependencies (Node.js + Vite) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY web/ web/
COPY vite.config.js tailwind.config.js ./
# 強制每次 image build 都重跑 Vite 前端打包。
# Zeabur 會過度快取 `RUN npm run build` 這層，導致改了 web/js 後前端 bundle 卻沒更新
# （JSON 與後端有更新、JS bundle 卻停在舊版）。當部署後前端沒更新時，bump 此值。
ARG FRONTEND_REV=2026-08-14-ton-bridge-exclusion-refresh-cooldown
RUN echo "frontend build rev: $FRONTEND_REV" && npm run build

FROM python:3.13-slim

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp \
    MPLCONFIGDIR=/tmp \
    NUMBA_CACHE_DIR=/tmp

WORKDIR /app

# --- Python dependencies ---
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# --- MCP server (Python, stdio) — crypto-trader via CoinGecko ---
# git clone 進 image，固定 commit 確保可重現 build。MCP_ENABLED=1 時由
# core/tools/mcp_loader.py 以 `python main.py` 啟動。免 Node、免 API key。
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && git clone https://github.com/SaintDoresh/Crypto-Trader-MCP-ClaudeDesktop.git \
        /app/mcp-servers/crypto-trader \
    && cd /app/mcp-servers/crypto-trader \
    && git checkout d3f5d1d236bff244a77cd205e37ffc097696b83c \
    && pip install -r requirements.txt \
    && rm -rf /var/lib/apt/lists/*

# --- Application code ---
COPY . .

# 確保 entrypoint 可執行（部署時自動跑 alembic upgrade head 再起服務）。
RUN chmod +x /app/docker-entrypoint.sh

# --- Overlay Vite-built frontend assets ---
COPY --from=builder /build/dist/static/index.html web/index.html
# 多頁 build（2026-08-14）：forum/*.html 是獨立頁面，Vite 已把它們的 module script
# 打包進 assets/ 並改寫 script tag。必須覆蓋 raw HTML，否則 module src（/js/*.js）
# 指向的 raw 檔會被下方刪除 → prod 404。
COPY --from=builder /build/dist/static/forum/ web/forum/
COPY --from=builder /build/dist/static/assets/ web/assets/
# Service worker 相關檔在 dist/static/ 根目錄（非 assets/），index.html 會用
# <script src="/static/sw-register.js"> 引用，workbox-*.js 是 sw.js 的依賴。
# 這些檔經由 /static mount 服務在 /static/sw.js 等路徑；後端 /sw.js 路由
# 另外服務同一份（送 Service-Worker-Allowed header）。
COPY --from=builder /build/dist/static/sw.js web/sw.js
COPY --from=builder /build/dist/static/sw-register.js web/sw-register.js
COPY --from=builder /build/dist/static/workbox-*.js web/

# index.html 以 classic <script> 載入 early-init.js / click-delegator.js /
# memory-manager.js / skill-manager.js / safety-banner.js（必須先於/獨立於
# bundle 執行，Vite 不打包），
# 清理時必須保留這幾支。logger.js 由 forum/*.html 以 classic script 載入，同樣保留。
# scam-tracker/*.html 與 governance/index.html 不在 Vite 多頁 build input，
# 以 classic 頁相容橋 classic-compat{,-app}.js（module）載入共用層並掛回
# window（2026-08-20 線上 404 事故後補；app.js 不在橋內——其 top-level
# AppStore 依賴在子頁會炸，且 8/14 前行為即是如此。tests/test_frontend_static_refs.py
# 會持續看守一致性）。
# 其餘 raw js（SPA 與 forum 多頁 build 的 module）已由 Vite 打包進 assets/。
RUN find /app/web/js -maxdepth 1 -type f -name "*.js" \
        ! -name "early-init.js" ! -name "click-delegator.js" ! -name "memory-manager.js" \
        ! -name "skill-manager.js" \
                ! -name "error-boundary.js" \
                ! -name "offline-banner.js" ! -name "logger.js" \
                ! -name "safety-banner.js" \
        ! -name "ui-shell.js" ! -name "auth.js" \
        ! -name "apiKeyManager.js" ! -name "i18n.js" \
        ! -name "utils.js" ! -name "api-client.js" \
        ! -name "classic-compat.js" ! -name "classic-compat-app.js" \
        ! -name "subpage-boot.js" \
        ! -name "nav-config.js" \
        ! -name "site-sidebar.js" \
        ! -name "components/content-modal.js" -delete \
    && find /app -type d -name "__pycache__" -prune -exec rm -rf {} + \
    && find /app -type f -name "*.py[co]" -delete \
    && addgroup --system app \
    && adduser --system --ingroup app --home /app appuser \
    && mkdir -p /app/data /app/config/keys /tmp/pycache \
    && chown -R appuser:app /app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)" || exit 1

USER appuser

# 透過 entrypoint 先套用 DB migrations，再啟動 gunicorn。
# （Zeabur 上的 Telegram bot 服務以自訂啟動指令覆寫此 CMD，不受影響。）
CMD ["sh", "/app/docker-entrypoint.sh"]
