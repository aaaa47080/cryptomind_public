# CLAUDE.md — CryptoMind Pi DApp

**Project owner: DANNY** | All major decisions confirmed by DANNY.

---

## Project intro

**Pi Crypto Insight** — AI-driven cryptocurrency analysis × community ecosystem.

| Layer | Tech |
|------|------|
| Backend | FastAPI + SQLAlchemy + PostgreSQL |
| Frontend | Vanilla JS (ES Modules) |
| AI | LangGraph + OpenAI |
| Testing | pytest + Playwright |

---

## Important principle: simple problems get simple solutions

> Don't over-engineer just to look "engineering-flavored." Do a simple thing in the most direct way.
> - Adding a field? Add it directly; don't abstract it into a factory.
> - Changing a line of text? Change it directly; don't build a config system.
> - Fixing a bug? Find the root cause and fix it with the smallest change.

---

## Auto-execute (no need to ask)

The following types of changes Claude can do directly:

- Syntax errors, obvious bug fixes
- Adding `try-catch`, null checks, and other defensive handling
- Minor API endpoint fixes (no behavior change)
- Frontend error message improvements
- Completing JS `import` statements (ES Modules)
- CSS / UI adjustments (no functional impact)
- SQLAlchemy subquery fixes
- Test mode / sandbox configuration fixes

## Must ask first (do not decide on your own)

- Authentication / authorization logic
- Database schema changes
- Any payment / money-flow related code
- How user data is handled
- Adding package dependencies
- TON Connect SDK integration changes
- TON payment flow adjustments

---

## Common commands

```bash
# Start backend
cd D:/ton/stock_agent_ton && python api_server.py

# Check port 8080 status
netstat -ano | grep 8080

# Terminate a specific PID
python -c "import os,signal; os.kill(<PID>, signal.SIGTERM)"

# Check JS syntax
node --check web/js/<file>.js

# Run tests
pytest                              # all
pytest tests/<file>.py              # single file
pytest -m unit                      # unit tests only
pytest -m e2e                       # E2E browser tests

# Python linting
ruff check .
ruff format .

# Dev login (for testing)
# POST /api/user/dev-login
# body: {"test_mode_confirmation": "I_UNDERSTAND_THE_RISKS"}
```

---

## Important paths

```
api_server.py              # Backend entry
api/routers/               # API route layer
  user.py / forum/ / friends.py / premium.py ...

web/index.html             # Frontend entry
web/js/main.js             # ES Modules entry
web/js/
  auth.js                  # Auth
  ton-auth.js              # TON Connect SDK integration
  forum-app.js             # Forum
  friends.js               # Friends
  premium.js               # Paid features (depends on loadPrices from forum-config.js)
  forum-config.js          # Forum config & Pi price

tests/                     # pytest tests
tests/e2e/                 # Playwright E2E tests
```

---

## Browser test flow

1. Start server: `python api_server.py`
2. Automate browser via Playwright MCP
3. Dev login: `POST /api/user/dev-login`
4. Test each tab: `#friends`, `#forum`, `#settings`
5. Find issue → check whether it falls under "Auto-execute" → fix directly or ask first

---

## Response style

- **Give the solution directly**; don't write a long background section first.
- **Fix first, talk later** (when it fits the auto-execute rules); don't ask "are you sure?"
- If there are multiple approaches, **recommend the simplest first**, then mention others.
- Prefer diffs for code changes; don't paste entire files.
