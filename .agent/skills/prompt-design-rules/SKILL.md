# Prompt & Agent Design Rules

> This document defines the principles that must be followed when designing prompts and agents. All newly added or modified prompts/agents must conform to these rules.

## Core principles

### Boundary conditions > hardcoded cases

LLMs already have enough knowledge to do analysis and decision-making. Our job is to **define boundaries**, not to **teach it how to do things**.

| ✅ Correct: boundary conditions | ❌ Wrong: hardcoded cases (Few-shot) |
|------------------|------------------------------|
| Choose the corresponding agent based on the asset type | Use the crypto agent for BTC |
| The task description must convey the query intent | Write: comprehensive analysis (price + technical indicators + market sentiment + latest news) |
| Create parallel tasks for multiple independent assets | Create two tasks for BTC and TSMC |
| Do not route across types | Do not route cryptocurrency to the economic agent |

### Why avoid Few-shot?

1. **Bias**: The LLM may over-rely on specific cases, leading to poor handling of other assets.
2. **Inflexible**: Hardcoded cases cannot adapt to new scenarios.
3. **Maintenance cost**: Every new scenario requires adding new cases.
4. **The LLM already knows**: The LLM's training data already contains a large amount of financial knowledge; it does not need us to teach it.

---

## Prompt design rules

### 1. Structural specification

Every prompt must contain the following parts:

```yaml
prompt_name:
  description: "Briefly describe the purpose of this prompt"
  template: |
    ## Role
    [Define the agent's role; do not give specific cases]

    ## Output format
    [JSON or other format specification]

    ## Boundary rules
    ### [Rule category 1]
    - Boundary condition 1
    - Boundary condition 2

    ### [Rule category 2]
    - Boundary condition 1
    - Boundary condition 2

    ## Input variables
    {variable_name}
```

### 2. How to write boundary rules

**Correct example:**
```
### Status boundary
- direct_response: greetings, thanks, small talk (not involving data queries)
- clarify: brand-new conversation where the asset cannot be inferred from context
- ready: all other situations
```

**Wrong example:**
```
### Status examples
- User says "hello" → direct_response
- User says "what's the price of BTC" → ready
- User says "analyze it" but doesn't say what to analyze → clarify
```

### 3. Forbidden content

| Forbidden | Reason |
|------|------|
| Specific stock / ticker symbols (BTC, 2330, AAPL) | Causes bias |
| Specific company names (TSMC, Tesla) | Causes bias |
| Specific price / numeric examples | May cause format bias |
| "If the user asks X, then do Y" style conditions | Should be replaced by boundary conditions |
| Complete JSON output examples | May cause output format rigidity |

### 4. Allowed content

| Allowed | Notes |
|------|------|
| Generic placeholders (<asset>, <ASSET>) | Does not specify concrete values |
| Boundary conditions (when A, when B) | Defines decision boundaries |
| Format specifications (JSON structure, field names) | Ensures parseable output |
| Role definitions (you are an analyst, you are an assistant) | Sets the context |

---

## Agent design rules

### 1. Agent registration specification

```python
agent_registry.register(agent, AgentMetadata(
    name="agent_name",           # lowercase, underscore-separated
    display_name="Agent name",   # display name
    description="Describe the agent's capability scope",  # do not list specific cases
    capabilities=["capability1", "capability2"],      # generic capability description
    allowed_tools=_tools("agent_name"),   # fetch from DB or config
    priority=10,                 # priority
))
```

### 2. How to write the description

**Correct:**
```
Cryptocurrency professional analyst — provides real-time price, technical indicators, market sentiment, and latest news. Does not directly provide trading decisions.
```

**Wrong:**
```
Cryptocurrency analyst — can query the prices of BTC, ETH, SOL, and analyze Bitcoin's RSI and MACD.
```

### 3. How to write capabilities

**Correct:**
```python
capabilities=["technical analysis", "market sentiment", "price query", "news"]
```

**Wrong:**
```python
capabilities=["BTC analysis", "ETH price", "query Bitcoin news"]
```

---

## Checklist

Before submitting any prompt or agent change, please confirm:

- [ ] No specific stock codes or ticker symbols used
- [ ] No specific company names used
- [ ] Rules are described by boundary conditions, not specific cases
- [ ] No complete input/output examples
- [ ] Agent description describes the capability scope, without listing specific assets
- [ ] Capabilities are generic abilities, not specific operations

---

## File locations

| Content | Location |
|------|------|
| Agent prompts | `core/agents/prompts/<agent_name>.yaml` |
| Agent implementation | `core/agents/agents/<agent_name>_agent.py` |
| Agent registration | `core/agents/bootstrap.py` |
| Tool definitions | `core/agents/tools.py` or `core/tools/<category>_tools.py` |

---

## Example comparison

### Wrong prompt (Few-shot style)

```yaml
intent_understanding:
  template: |
    Analyze the user query and choose the correct agent:

    Examples:
    - User: "What's the price of BTC" → crypto agent
    - User: "TSMC stock price" → tw_stock agent
    - User: "Apple earnings report" → us_stock agent

    When the user asks "is it worth buying", the task description should say:
    "Comprehensive analysis of BTC: query real-time price, technical indicators (RSI/MACD/MA), fear & greed index"
```

### Correct prompt (boundary-condition style)

```yaml
intent_understanding:
  template: |
    Based on the user query, plan the tasks that need to be executed.

    ## Boundary rules

    ### Agent routing boundary
    Choose the corresponding agent based on the asset type; do not route across types.

    ### Task description boundary
    The task description must clearly convey the user's **query intent** so that the agent can decide which tools to use on its own.

    ### Context inference boundary
    When the user's question does not explicitly mention an asset:
    - First infer from the conversation history
    - Only return clarify when it is **completely impossible to infer**
```

---

## Update log

| Date | Change |
|------|---------|
| 2026-03-07 | Initial creation |
