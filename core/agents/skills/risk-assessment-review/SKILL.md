---
name: risk-assessment-review
description: "Risk Management Committee — adapted from TradingAgents' Risk Management Committee. After giving investment advice, review whether the risk disclosure is adequate and whether the stop-loss / position sizing is reasonable, from three risk inclinations: aggressive, neutral, and conservative. Ensures the advice has not only bull/bear sides but also risk protection."
applies_to: [chat, crypto, us_stock, tw_stock, global_stock, commodity, forex]
priority: 6
eager_load: true  # 金融建議必須有風險審核，命中時強制注入
auto_fire_keywords: [風險, 止損, 止蝕, 倉位, 部位, 資金管理, 槓桿, 最大回撤, drawdown, 風險承受, risk, stop loss, position sizing, leverage, 適合買嗎, 值得買嗎, 該進場嗎, 該買嗎, all in, 重倉, 滿倉]
recommended_tools: ['get_fear_and_greed_index', 'technical_analysis', 'get_crypto_price']
---

# Risk Management Committee (adapted from TradingAgents Risk Management Committee)

## When to Use
When giving investment advice (especially buy/sell judgments), attach a risk review. Also applies when the user asks risk-related questions:
- "Is TON a good buy?" → advice + risk review
- "Should I go all in?" → strong trigger (high-risk behavior)
- "Where should I set the stop loss?" → direct trigger
- "How should I size the position?" → direct trigger

**Division of labor with other skills**:
- investment-judgment: structured judgment (bull / bear / synthesis)
- bull-bear-debate: bull vs bear debate stress test
- **risk-assessment-review (this skill)**: risk-protection review (three inclinations + stop-loss / position sizing)
- market-risk-assessment: overall market risk / sentiment data

## Review Mechanism (adapted from TradingAgents, three risk inclinations + mutual critique)

TradingAgents' risk committee reviews trading decisions from three angles, **and the committee members refute each other**.
We use a single LLM to simulate the three members' perspectives.

**Key (adapted from TradingAgents' debate-style risk control)**:
Each member does not merely state their own view — they **challenge the blind spots of the other members**.
The conservative member challenges the aggressive member's "excessive optimism"; the aggressive member challenges the conservative member's "missed opportunity".

### Member 1: Aggressive (Risk-Seeking)
From the angle of "pursuing maximum return", **refute the conservative side's excessive worry**:
```
🔴 Aggressive view:
- Is this advice too conservative? Missing the upside opportunity?
- If confidence is high, should we add size?
- Response to the conservative side: "The risk you worry about has a low probability, because the data shows..."
- Risk: excessive aggression can cause severe damage during a pullback (must acknowledge one's own risk)
```

### Member 2: Neutral (Risk-Neutral)
From the angle of "balancing return and risk", **mediate between the two extremes**:
```
🟡 Neutral view:
- Is the risk/reward ratio of the advice reasonable?
- Does the position sizing follow general money-management principles?
- Are there overlooked neutral risks (liquidity, correlation)?
```

### Member 3: Conservative (Risk-Averse) — core: challenge the aggressive side's optimism
From the angle of "protecting principal", **actively challenge the optimistic assumptions of the aggressive/neutral sides**:
```
🟢 Conservative view:
- What is the worst case? Can it be tolerated?
- Is the stop-loss point explicit? Is one set?
- Are there undisclosed tail risks (black swan, liquidity dry-up)?
- Response to the aggressive side: "You focus on the bullish signal but ignore the risks,
  if the risk materializes, the loss would be significant — is this tolerable?"
- For beginners / small-capital users, is the advice too risky?
```

### Risk Resolution
After the three members review, issue the risk-control recommendation:
```
🛡️ Risk Resolution:
- Stop-loss recommendation: if entering, set a stop-loss at a key technical level (rationale: technical support or a fixed percentage)
- Position recommendation: no more than a defined percentage of total capital, with the rationale stated
- Risk level: low, medium, or high — with a one-line rationale
- Special warning: if there are high-risk signs (all-in, heavy position, leverage), warn strongly
```

## Output Format (appended after the investment advice)

```
🛡️ Risk Review
Stop-loss reference: the key level used, with rationale
Suggested position: a defined percentage of total capital
Risk level: low, medium, or high

💡 Risk reminder: [the single most important risk reminder — e.g., "high volatility; only invest an amount you can afford to lose entirely"]

⚠️ The above does not constitute investment advice. Investing carries risk; decide based on your own situation.
```

## Position / Money-Management Principles (general guidance)

Regardless of the asset, the following principles apply (not customized advice, but a general framework):
- **A single asset should not exceed 5–20% of total capital** (depending on risk level)
- **Crypto leverage is extremely high-risk**; not recommended for beginners
- **Set a stop-loss**: before entering, decide "at what price I admit I'm wrong and exit"
- **Use only money you can afford to lose entirely** for high-volatility assets

## Strong Warnings for Special Cases

When the following high-risk behaviors are detected, **a strong warning is mandatory** (not just listing risks, but explicitly opposing):
- "All-in / full position / bet everything" → strongly advise diversification
- "Mortgaging the house / borrowing to invest" → strongly oppose
- "High leverage" → warn about liquidation risk
- "Copy-trading / buying on tips" → warn about information-source risk
