---
name: Add V4 Agent
description: How to add a new SubAgent to the Agent V4 system. Use when the user asks to add a new agent type or specialist.
---

# Add a New Agent to Agent V4

Follow these steps exactly to add a new agent.

## Step 1: Create agent file

Create `core/agents/agents/new_agent.py`:

```python
from langchain_core.messages import HumanMessage
from ..base import SubAgent
from ..models import SubTask, AgentResult


class NewAgent(SubAgent):

    @property
    def name(self) -> str:
        return "new_agent_name"  # must match the name used in bootstrap registration

    def execute(self, task: SubTask) -> AgentResult:
        """Main execution logic."""
        symbol = self._extract_symbol(task.description)

        # Use tools assigned to this agent
        result = self._use_tool("tool_name", {"symbol": symbol})
        if not result.success:
            return AgentResult(
                success=False,
                message=f"Tool execution failed: {result.error}",
                agent_name=self.name,
            )

        # Optional: use LLM for analysis
        prompt = f"Analyze based on the following data:\n{result.data}"
        response = self.llm.invoke([HumanMessage(content=prompt)])

        return AgentResult(
            success=True,
            message=response.content,
            agent_name=self.name,
            data=result.data,
        )

    def _extract_symbol(self, text: str) -> str:
        import re
        symbols = ["BTC", "ETH", "PI", "SOL", "DOGE", "XRP", "BNB"]
        text_upper = text.upper()
        for s in symbols:
            if s in text_upper:
                return s
        match = re.search(r'\b([A-Z]{2,10})\b', text_upper)
        return match.group(1) if match else "BTC"
```

**Rules:**
- Must inherit from `SubAgent`
- Must implement `name` property and `execute()` method
- `name` property return value must match the registration name in bootstrap.py
- Use `self._use_tool(name, params)` to call tools — returns `ToolResult(success, data, error)`
- Return `AgentResult(success, message, agent_name, data=optional)`

## Step 2: Create prompt YAML

Create `core/agents/prompts/new_agent.yaml`:

```yaml
system:
  description: "NewAgent system prompt"
  template: |
    You are an AI Agent specialized in [domain] analysis.

    ✅ What you can do:
    - [List capability 1]
    - [List capability 2]

    📌 Response rules:
    - Respond in the user's language
    - Keep the response well-structured and highlight key points
    - Back up the analysis with data

response:
  description: "NewAgent response prompt; receives query, data"
  template: |
    User query: {query}

    Available data:
    {data}

    Please provide a professional analysis based on the data. Respond in the user's language.
```

Then use it in your agent:
```python
from ..prompt_registry import PromptRegistry

system_prompt = PromptRegistry.get("new_agent", "system")
response_prompt = PromptRegistry.render("new_agent", "response", query=query, data=data)
```

## Step 3: Export in `__init__.py`

Edit `core/agents/agents/__init__.py`:

```python
from .new_agent import NewAgent

__all__ = ["TechAgent", "NewsAgent", "ChatAgent", "NewAgent"]
```

## Step 4: Create tools if needed

If the agent needs new tools, follow the **Add V4 Tool** skill first.

## Step 5: Register in `core/agents/bootstrap.py`

```python
from .agents import ..., NewAgent
from .tools import ..., new_tool  # if new tools were created

# Create agent with tool registry
new_agent = NewAgent(llm_client, tool_registry, hitl)
agent_registry.register(new_agent, AgentMetadata(
    name="new_agent_name",       # must match agent's name property
    display_name="New Agent",
    description="Describe what this Agent does. What kind of queries suit it. What it does not handle.",
    capabilities=["capability1", "capability2"],
    allowed_tools=["new_tool", "get_crypto_price"],
    priority=10,  # 1=fallback, 10=specialist
))
```

**CRITICAL: `description` is the most important field** — the Manager LLM uses this to decide which agent handles which query. Include:
- What the agent does
- Example queries that should go to this agent
- What it does NOT handle (if easily confused with other agents)

## Step 6: Verify

```bash
python -c "from core.agents.bootstrap import bootstrap; from utils.llm_client import LLMClientFactory; llm = LLMClientFactory.create_client('openai', 'gpt-4o-mini'); m = bootstrap(llm); print('Agents:', [a.name for a in m.agent_registry.list_all()])"
```

Then test with a query that should route to your new agent.

## Files Changed

| File | Change |
|---|---|
| `core/agents/agents/new_agent.py` | **[NEW]** Agent class |
| `core/agents/prompts/new_agent.yaml` | **[NEW]** Prompt templates |
| `core/agents/agents/__init__.py` | Export new agent |
| `core/agents/tools.py` | New @tool functions (if needed) |
| `core/agents/bootstrap.py` | Create + register agent |
| **manager.py** | **No change needed** |
