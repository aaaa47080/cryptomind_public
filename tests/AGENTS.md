# AGENTS.md — tests/

> Test layer: pytest + Playwright + 5 CI workflows. See root `AGENTS.md` for stack / anti-pattern common rules.

## STRUCTURE (263 test files)

| Path | Count | Role |
|------|-------|------|
| `conftest.py` | 1 | Main fixtures: `app`, `client`, `auth_headers`, `admin_headers`, `mock_llm_client` |
| `e2e/conftest.py` | 1 | Static server :8770, browser, page, API stubs |
| `e2e/pages/` | 3 | PO pattern — `base_page.py` (BasePage) + `chat_page.py` + `settings_page.py` |
| `e2e/test_*.py` | 13 | chat, navigation, settings, static_asset 等（以 `ls tests/e2e/test_*.py` 為準） |
| `test_data/` | 4 | data_processor, data_fetcher, indicator_calculator |
| `test_routers/` | 6 | admin_auth, negative_paths, system, analysis_idor, user_session |
| `security/` | 3 | test_security_hardening, test_cdn_sri, test_csp_and_exception_regression |
| `test_*.py` (root) | 100+ | unit + integration |

## MARKERS (5)

`asyncio` · `unit` (~57) · `integration` (~15) · `e2e` (~20) · `slow`. `asyncio_mode=auto`; coverage `--cov=core --cov=api`.

## CI WORKFLOWS (6)

| File | Trigger | Purpose |
|------|---------|---------|
| `.github/workflows/ci.yml` | push PR → main/develop | ruff lint+format, unit/integration, i18n JSON validation, auto-PR |
| `.github/workflows/e2e.yml` | push → main/develop | Playwright E2E (`continue-on-error: true`, ignores 6 flaky) |
| `.github/workflows/deploy.yml` | push main + manual | Docker build, Vite bundle verify, smoke tests, auto-rollback |
| `.github/workflows/test-suite.yml` | push PR + manual | Critical backend + static asset + autonomous data-policy E2E |
| `.github/workflows/dependency-weekly-audit.yml` | weekly | pip-audit + lockfile refresh |

## KEY COMMANDS

```bash
pytest -m "not e2e and not integration" -o addopts='-v --tb=short --no-cov'   # fast
pytest -m e2e --timeout=120                                                  # e2e only
pytest tests/test_analysis_policy.py tests/test_analysis_response_metadata.py tests/test_api_models.py -q  # critical CI subset
```

## E2E PATTERN (Playwright PO)

- `pages/base_page.py` — helpers (click, fill, wait, toast, sidebar, tab). Concrete POs extend BasePage.
- Static server :8770 serves `web/`. API stubs in `e2e/conftest.py`.
- localStorage seeds a mock user; mock WebSocket.

## MOCKING PATTERNS
- `AsyncMock` for async LLM: `manager._extract_market_entities_llm = AsyncMock(return_value=_all_none(crypto="BTC"))`
- `patch.dict("os.environ", {"ENVIRONMENT": "development"})` for env vars
- `MagicMock` for request objects

## TEST MODE SETUP (`tests/conftest.py`)

```python
TEST_MODE=true
TEST_MODE_CONFIRMATION=I_UNDERSTAND_THE_RISKS
DATABASE_URL=postgresql://test:test@localhost:5432/test
REDIS_URL=memory://
```

## ANTI-PATTERNS / FRAGILE TESTS

- Bare `except Exception:` — `providers/{yahoo_provider,okx_websocket,base_provider}.py`, `data/data_fetcher.py`, `api/health.py` (**HIGH**, violates root prohibition)
- `continue-on-error: true` + 6 ignored E2E files — `.github/workflows/e2e.yml:46-56` (MED, known-flaky)
- `AsyncMock` repeated 24x — (已移除) (LOW)

## TOP FILES

1. `pytest.ini` + `tests/conftest.py` — markers, coverage, main fixtures
2. `tests/e2e/{conftest.py, pages/base_page.py}` — E2E fixtures + BasePage PO
3. `.github/workflows/{ci, e2e, deploy, test-suite}.yml` — CI gates + deploy smoke
4. `tests/test_routers/test_admin_auth.py` — Admin auth
5. `tests/security/test_security_hardening.py` — Security regression

## SEE ALSO
- Root `AGENTS.md` · `scripts/AGENTS.md` · `api/AGENTS.md`
