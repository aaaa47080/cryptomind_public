# AGENTS.md — api/

> FastAPI entry + route layer. See root `AGENTS.md` for stack / anti-pattern common rules.

## DUAL ENTRY POINTS

| File | Role |
|------|------|
| `api_server.py` | **CANONICAL** — dev + startup (`python api_server.py`, port 8080) |
| `api/main.py` | **Gunicorn/Zeabur shim** — `from api.main import app`, only re-exports `api_server.py`'s `app` |

Both point to the same `app` object. To change app settings → edit `api_server.py`.

## TOP-LEVEL MODULES (api/)

| File | Role |
|------|------|
| `deps.py` | Auth: `get_current_user`, `require_admin`, JWT + revoked tokens |
| `lifespan.py` | Startup/shutdown: DB init, background tasks, V4 agent bootstrap |
| `middleware_setup.py` | All middleware registration (order see below) |
| `services.py` | Background: market pulse, funding rates, price alerts |
| `models.py` | Pydantic schemas; `utils.py` `run_sync()`; `globals.py` shared state |
| `health.py`, `ton_verification.py`, `symbols.py`, etc. | Standalone utilities |

## ROUTER LAYOUT (36 top-level router modules + 4 sub-packages; 37 include_router calls)

**Top-level**: `system`, `analysis` (V4 SSE), `user`, `premium`, `friends`, `messages`, `notifications`, `governance`, `alerts`, `tools`, `audit`, `swap`, `memory`, `skills`, `agent_presets`, `discover`, `studio`, `telegram_link`, `guard_management`, `guard_v1`, `trust`, `wallet_monitor`, `market`, `health`（完整清單見 `api_server.py` 的 `include_router` 區）。

**Sub-packages** (`<name>/__init__.py` builds parent `APIRouter` + `include_router` + prefix):
- `forum/` — boards, posts, comments, tips, tags, me
- `market/` — rest, websocket, helpers
- `scam_tracker/` — reports, votes, comments (`/api/scam-tracker`)
- `admin/` — users, forum, config, stats, notifications

**Market routers** (top-level): `twstock`, `usstock`, `astock`, `hkstock`, `jpstock`, `instock`, `krstock`, `forex`, `commodity`.

## MIDDLEWARE ORDER (registration)

1. Global exception handler (production: hides details)
2. Rate limit (slowapi, Redis with in-memory fallback)
3. Audit logging (file + selective DB)
4. CORS (`CORS_ORIGINS` env, warn on `*`)
5. GZip (>1KB)
6. Security headers (CSP+HSTS in prod)
7. `TrustedHostMiddleware` (prod only, `ALLOWED_HOSTS` required)
8. Request ID (`X-Request-ID`)

## KEY PATTERNS

- **Production safety** (`api_server.py:100-122`): refuses to start if `TEST_MODE=true` or `API_KEY_ENCRYPTION_SECRET < 32 chars`
- **Background tasks** (lifespan): market pulse, funding rates, price alerts, audit cleanup — all started via `asyncio.create_task` on startup
- **Token revocation** (`deps.py:64-148`): in-memory + `data/revoked_tokens.json` across processes
- **`run_sync()` bridge**: call sync DB functions inside async endpoints (see anti-patterns)
- **TON Connect manifest** (`api_server.py`): serves `/tonconnect-manifest.json` for TON Connect wallets to read
- **Static mounting**: `/js`, `/css`, `/img`, `/assets`, `/scam-tracker`, `/legal`

## TOP FILES BY IMPORTANCE

| File | LOC | Role |
|------|-----|------|
| `api_server.py` (repo root) | 599 | App factory + all router registration |
| `deps.py` | 573 | Auth (JWT, revocation) |
| `services.py` | 1002 | Background tasks |
| `routers/analysis.py` | 1752 | V4 ManagerAgent + chat SSE |
| `routers/governance.py` | 620 | Community voting |

## ANTI-PATTERNS (CRITICAL)

1. **`except Exception:` (bare)** — 12 files, 30 occurrences:
   `health.py`, `services.py`, `premium.py`, `routers/market/websocket.py`, `admin/notifications.py`, `admin/users.py` (3x), `yf_helpers.py` (7x), `usstock.py` (3x), `forum/comments.py` (5x), `forex.py` (2x), `forum/boards.py` (2x), `audit.py` (2x).
   These catch `KeyboardInterrupt`/`SystemExit`/`asyncio.CancelledError`.

2. **Sync DB in async** — 11 files, 35 occurrences: `conn.commit()` + `conn.close()` directly inside async functions.
   Affected: `admin/users.py`, `admin/stats.py`, `admin/config.py`, `premium.py`, `forum/tips.py`, `audit.py`, `health.py`.
   Currently mitigated with `await run_sync(...)` — still blocks the thread pool. Goal: migrate all to async SQLAlchemy `session.execute()`.

3. **Inconsistent auth**: mixes `Depends(get_current_user)` / `verify_admin_key` decorator / both. `system.py` uses `verify_admin_key` instead of `require_admin`.

## SEE ALSO
- Root `AGENTS.md` · `core/AGENTS.md` · `tests/AGENTS.md`
