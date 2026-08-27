# AGENTS.md — CryptoMind / TON Development Guide

> Project owner: DANNY. Design decisions involving payments, login/auth models, database schema, or new services must be confirmed by DANNY.

## Overview

CryptoMind is an AI-driven crypto & stock analysis platform, including forum, notifications, BYOK, and TON Connect.

Stack: FastAPI, async SQLAlchemy/PostgreSQL, LangGraph/OpenRouter, Vanilla JS/Tailwind, TON Connect.

Main entry points: `api_server.py` (dev and production app) and `api/main.py` (Gunicorn shim).

Python 3.13 (see `.python-version`). Local venv: use `.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Linux/Docker/production. References to `.venv/bin/python` in docs must be substituted with `python` or `.venv/Scripts/python.exe` on Windows.

## Directory Guide

| Need | Location |
|---|---|
| API routes & auth | `api/routers/`, `api/deps.py`, `api/middleware_setup.py` |
| Agents, tools & validators | `core/agents/`, `core/tools/`, `core/validators/` |
| Data layer | `core/orm/` (target async layer), `core/database/` (legacy layer being migrated) |
| Frontend & static pages | `web/js/`, `web/forum/`, `web/scam-tracker/`, `web/governance/` |
| Tests | `tests/`; E2E in `tests/e2e/` |
| Deploy & ops | `Dockerfile`, `docker-compose.yml`, `.github/workflows/`, `scripts/` |

Sub-directory `AGENTS.md` files supplement the rules for that layer; read the applicable file before modifying.

### Sub-directory rules & important files

| Layer | File | Supplement |
|---|---|---|
| Frontend | `web/AGENTS.md` | SPA build (Vite at repo root), 106 JS modules, 21 tabs, i18n |
| API | `api/AGENTS.md` | Routes, auth, middleware |
| Core | `core/AGENTS.md` | Agents, tools, ORM |
| Tests | `tests/AGENTS.md` | Testing conventions |
| Scripts | `scripts/AGENTS.md` | Ops & CI scripts |

| Important file | When to read |
|---|---|
| `docs/DESIGN_SYSTEM.md` | Before changing any frontend visuals (tokens, colors, fonts, border-radius) — single source of truth |
| `docs/development_workflow.md` | Standard workflow when changing agent behavior (incl. commit/PR SOP) |
| `docs/plans/TEMPLATE.md` | Design + implementation template when planning a major feature |

## Security Baseline (must follow)

### Keys & secrets

- Secrets are injected into the environment only by the deploy platform / secret manager; `.env` is local-only and must never be tracked. Real values must never be placed in `.env.example`, tests, logs, error responses, or frontend bundles.
- Production must set `JWT_SECRET_KEY` and `API_KEY_ENCRYPTION_SECRET` of at least 32 characters. The application refuses to start with incomplete configuration.
- User BYOK keys may only be written to the database after encryption via `utils/encryption.py`. Production must never read, create, or rotate file-based keys; dev `config/api_key_encryption.json` must be gitignored, directory `0700`, file `0600`.
- For an externally managed `API_KEY_ENCRYPTION_SECRET`, never call the file-based `rotate_encryption_key()`. Rotation must go through a controlled ops process: backup, decrypt-and-re-encrypt with new/old key, full verification, then switch and revoke the old secret; never simply replace the env value.
- JWT is delivered to the browser only via `HttpOnly` cookie; do not pass tokens in response JSON, `localStorage`, `sessionStorage`, query strings, or WebSocket messages. Bearer headers are only for non-browser APIs.
- Run `python scripts/check_secrets.py` on every change; if secrets were ever exposed in git history, revoke first, then use BFG / git-filter-repo to purge and force all users to re-clone.

### Production boundary

- When `ENVIRONMENT=production`, `TEST_MODE` must be false; no auth-bypass fallbacks may be added.
- `CORS_ORIGINS` must be explicit allowed HTTPS origins; `*` is forbidden; `ALLOWED_HOSTS` is required. Missing values must fail closed.
- Production rate limiting must use shared Redis (`REDIS_URL` or `REDIS_HOST`); replacing it with `memory://` is forbidden, as it breaks across workers and restarts.
- Every data-mutating route must have authentication, object ownership / role check, Pydantic boundary validation, and an appropriate rate limit.
- SQL is restricted to ORM or parameterized queries. No SQL concatenation, f-string SQL, or passing user input to the shell.
- When inserting user content into the DOM, use existing safe-rendering / escape flows; evaluate CSP nonce before adding any inline script.

### Unacceptable patterns

- `type: ignore`, `@ts-ignore`, `as any`.
- `except Exception:`; catch specific exceptions and preserve `CancelledError` / system-interrupt behavior.
- Hardcoded secrets, token logging, debug output of PII / API keys.
- Performing sync DB or network I/O directly inside async routes; use an async repository or the `run_sync()` bridge (and plan the migration).

## Development conventions

- Python: Ruff (E4/E7/E9/F/I), Pydantic validation, UTC time, soft delete.
- JavaScript: ESLint, single quotes, semicolons, Prettier 100 columns. Prefer `web/js/api-client.js` for new HTTP calls; same-origin cookie sessions must use `credentials: 'include'`.
- Frontend CSS: Tailwind source is `web/css/tailwind-src.css`, rebuilt via `npm run build:css` (minify output `web/css/tailwind-built.css`); `npm run dev` / `npm run build` go through Vite (see `package.json`).
- Write tests before implementing new features or fixes; at minimum cover success, rejection, and boundary cases.
- Preserve users' existing changes; do not use `git reset --hard` or unauthorized destructive DB / git-history commands.

## Authorization boundaries

Can handle directly: clear bugs, security hardening, input validation, tests, copy, and CSS.

Must confirm first: product changes to login / permission models, schema migrations, TON payment / pricing logic, new agents or external services, running destructive ops scripts. When any of these is triggered, start a design doc using `docs/plans/TEMPLATE.md` and only proceed after DANNY confirms Status = Approved.

## LLM Observability (Langfuse)

- Langfuse is an **optional** observability layer; it auto-no-ops when `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are unset or `TEST_MODE=true`, with no impact on any main flow.
- Integration points: `utils/langfuse_init.py` wraps init + the LangChain `CallbackHandler`; `api/lifespan.py` calls init and flush on startup/shutdown; `core/agents/manager/_main.py:_TracedGraph` injects the handler into `config["callbacks"]` on `ainvoke` / `invoke`.
- The LangChain 1.x callback mechanism automatically propagates the handler to inner LLM / tool / ReAct loops, so all calls of the cryptomind agent are traced.
- **BYOK API keys never enter traces** (keys are injected at LLM client construction, not inside prompts).
- ⚠️ Langfuse Cloud receives user prompt/response content (including crypto / stock queries). For compliance concerns, use self-host, or take it offline immediately via `LANGFUSE_TRACING_ENABLED=false`.


## Verification commands

```bash
.venv/bin/python -m pytest -m "not e2e" -o addopts='-v --tb=short --no-cov'
.venv/bin/python -m ruff check .
.venv/bin/python scripts/check_secrets.py
./scripts/run_autonomous_policy_checks.sh
./scripts/security-check.sh
```

Before deployment, always verify: production env guard, cookie flags, explicit CORS/Host, BYOK encrypt/decrypt, permission-denial paths, and payment replay protection.

---

Last updated: 2026-07 (after security audit)
