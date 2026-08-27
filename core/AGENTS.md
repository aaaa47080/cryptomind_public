# AGENTS.md — core/

> Core business logic: agent system, data layer, providers, tools, validators. See root `AGENTS.md` for common rules.

## SUBDIRECTORY MAP

| Dir | Role |
|-----|------|
| `agents/` | 49 files — LangGraph multi-agent (8 sub-agents, 8 mixins, prompts, descriptions) |
| `database/` | 29 — Raw SQL (psycopg2), in transition |
| `orm/` | 23 — Async SQLAlchemy 2.0 (target layer) |
| `providers/` | 4 — Market data abstraction |
| `tools/` | 23 — Tool implementations + `crypto_modules/` |
| `validators/` | 4 — content, governance, pi_address |

## AGENT SYSTEM

- Entry: `manager.py` (facade) + `bootstrap.py` (1472)

### ManagerAgent (LangGraph `StateGraph`)

`core/agents/manager/_main.py` (477) — 8 mixins: `Nodes` (graph) · `Routing` · `EntityResolver` · `Response` · `LLMInvoke` · `Memory` · `Execution` · `Manager` (composition).

### Sub-Agents

All extend `BaseReactAgent` (`base_react_agent.py`, 579) using `langchain.agents.create_agent` (migrated 2026-07 from deprecated `langgraph.prebuilt.create_react_agent`): crypto, us_stock, tw_stock, commodity, forex, economic, tech, global_stock, chat.

Support: `models.py` (579, Pydantic), `tool_registry.py`, `tool_compactor.py` (477, prevents state flooding), `prompt_registry.py`, `analysis_policy.py` (routing), `model_router.py`. Main prompt: `prompts/manager.yaml` (28KB).

## DATABASE / ORM — DUAL LAYER (in transition)

- **Layer 1 Raw SQL** (`database/`): `psycopg2`, in transition
- **Layer 2 Async ORM** (`orm/`) — TARGET:
  - `models.py` (1075) — 30+ SQLAlchemy 2.0 models
  - `session.py` (192) — `using_session(session=None)` ctx: passed in → caller manages; omitted → auto create/commit/close
  - `repositories.py` — Repo pattern (`user_repo`, `chat_repo`, `forum_repo`, etc.)

## LLM PROVIDER ABSTRACTIONS (`core/providers/`)

- `base_provider.py` (259) — `StockDataProvider` ABC + factory `get_provider(market)`, TTL thread-safe cache, methods: `get_price`, `get_technicals`, `get_fundamentals`, `get_snapshot`
- Markets: `us`, `tw`, `hk`, `jp`, `kr`, `in`, `cn` — providers: `twse`, `us` (yfinance), `yahoo`

## TOOLS + VALIDATORS

- `core/tools/` — 23 files + `crypto_modules/`. `analysis_policy.py` provides membership-tier control (`free` vs `premium`).
- `core/validators/` — `content_filter.py`, `governance.py`, `pii_scrubber.py` / `forum_sanitizer.py`

## NOTABLE PATTERNS

- **Context budget** (`context_budget.py`): `CONTEXT_CHAR_BUDGET`, `history_exceeds_budget()` — caps prompt history
- **Memory**: `ExperienceStore` + `UserMemory`; per-session `MemorySaver` (512 max, FIFO)
- **Tool access**: `ToolAccessResolver` — controls tools by membership tier
- **Production guard** (`core/config.py:26-35`): multi-layer `TEST_MODE` safety checks

## ANTI-PATTERNS / WARNINGS

- `core/agents/manager/{response.py:33, nodes.py:458}` — hardcoded filter "XXX"/"N/A"/"error"
- `core/providers/{yahoo_provider.py:8, okx_websocket.py:3}` — bare `except Exception:` (violates root prohibition)

## TOP FILES

1. `core/agents/bootstrap.py` (1346) — Bootstrap
2. `core/orm/models.py` (1075) — 30+ DB models
3. `core/agents/{base_react_agent,models}.py` (579) — Sub-agent base + Pydantic
4. `core/agents/manager/_main.py` (477) — Manager graph + mixins
5. `core/providers/base_provider.py` (229) — Provider base
6. `core/{config,model_config}.py` — Production + LLM config

## SEE ALSO

- Root `AGENTS.md` — conventions, anti-patterns
- `api/AGENTS.md` — API layer calls this layer
- `web/AGENTS.md` — endpoints the frontend talks to
