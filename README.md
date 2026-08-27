[ 🇹🇼 中文版 (Chinese Version) ](README_CN.md)

# CryptoMind
## AI-Powered Crypto Analysis × Community Ecosystem

> **Combining AI-powered analysis with TON blockchain payments to create the ultimate cryptocurrency community platform**

### 🛡️ Trust Layer for AI Agents

CryptoMind is also a demonstration of **trustworthy AI agent governance** — a trust layer that wraps
the agent with authorization boundaries, policy gates, audit logs, and revocation. When the agent
acts on behalf of a user (querying wallets, submitting KYC, assessing scams), every action is:

- **Principal-bound** — the agent represents a verified TON wallet identity (ed25519 proof)
- **Authorization-scoped** — tier RBAC × risk-level classification limits what tools the agent may call
- **Policy-gated** — high-risk actions (wallet access, KYC, financial verdicts) require explicit human consent before execution (fail-closed)
- **Audit-logged** — every consent decision, high-risk execution, and revocation is traceable
- **Revocable** — the user can revoke authorization at any time; the agent stops immediately

See [`docs/TRUST_DESIGN.md`](docs/TRUST_DESIGN.md) for the full Governance Gap Memo mapping to the
six trust elements (Principal, Authorization, Tool boundary, Policy Gate, Audit Log, Expiry/Revocation).

An open-source project by independent developers, building AI-Agents that autonomously plan, use tools, and solve complex problems — from underlying data acquisition and robust backend infrastructure to high-level agent logic design.

We are looking for technical partners, business collaborations, and development sponsorship to pioneer the AI wave together.

---

## Core Value Proposition

### Why CryptoMind?

| Advantage | Description |
|-----------|-------------|
| 🧠 **Agent V4 Architecture** | Interactive multi-market analysis (Crypto, US Stocks, TW Stocks) |
| 💬 **PTT-Style Community** | Comprehensive discussion boards with native TON tipping |
| 💰 **TON Ecosystem Integration** | Seamless Web3 payments for posting, tipping, and membership |
| 🔐 **Privacy-First Design** | User data sovereignty, secure transactions |

### Unique Selling Points

- **First AI analysis platform** integrated with TON Connect
- **Interactive Agent V4 System** — Human-in-the-loop (HitL) intelligent planning & negotiation
- **Multi-Market Support** — Seamless tracking across Crypto, US Stocks, and TW Stocks
- **Complete community ecosystem** — Discussion + Social + Trading
- **Real-time multi-exchange data** — OKX + Binance unified interface

---

## Market Opportunity

### Target Markets

| Segment | Opportunity |
|---------|-------------|
| **Crypto Investors** | Seeking AI-assisted decision-making tools |
| **TON Ecosystem Users** | Growing user base lacking practical DApp applications |
| **Chinese-speaking Finance Community** | Advanced experience beyond PTT/Dcard |

### Competitive Advantages

| Dimension | CryptoMind | Traditional Analysis Tools | Generic Forums |
|-----------|-------------------|---------------------------|----------------|
| AI Analysis Depth | Multi-agent Manager orchestration | Single model | None |
| Payment Integration | TON blockchain native | Traditional payment | Ads/Subscription |
| Community Interaction | Posts + Tipping + Reputation | None | Basic features |
| Real-time Data | OKX + Binance | Single exchange | None |
| Privacy Protection | User data sovereignty | Centralized storage | Centralized |

### Entry Barriers

- Official TON Connect SDK integration certification
- Multi-exchange API integration expertise
- LangGraph AI agent technology accumulation

---

## Feature Highlights

### 🧠 Agent V4 Intelligent System

**Multi-Market Agent Architecture**

| Agent | Responsibility |
|-------|---------------|
| **Crypto Agent** | Cryptocurrency market data, on-chain analysis, and web3 news |
| **US Stock Agent** | NYSE/NASDAQ market data, SEC filings, and corporate news |
| **TW Stock Agent** | Taiwan market tickers, local institutional movements, and news |
| **Manager Agent** | Intelligent query classification and analysis flow orchestration |

**Interactive Plan Execution (Human-in-the-loop)**

```
User Query → [Manager Agent Classification]
                    ↓
        [Automatic Pre-research Data Gathering]
                    ↓
    [Propose Multi-step Execution Plan to User] ↔ User Negotiates/Modifies Plan
                    ↓
[Agents Execute Plan: Tech / Fundamentals / News]
                    ↓
          [Synthesize Final Report]
```

---

### Community Forum (PTT-Style)

**Board Categories**

| Board | Topics |
|-------|--------|
| 💎 Crypto | BTC, ETH, SOL, Altcoins |
| 📈 US Stocks | Tech stocks, ETFs, Options |
| 🏦 TW Stocks | TSMC, Financial stocks, ETFs |

**Interaction Mechanisms**

- **Post Categories** — Analysis / Questions / Tutorials / News / Discussion / Insights
- **Tag System** — #BTC #ETH #SOL for quick filtering
- **Voting** — Push (👍) / Boo (👎) affects author reputation
- **TON Tipping** — Direct P2P transfers to authors

---

### Social Features

| Feature | Description |
|---------|-------------|
| **Friend System** | Add friends, block users, view status |
| **Private Messaging** | Real-time chat (Premium members) |
| **Notification Center** | Friend requests, tips, system announcements |
| **Watchlist** | Track favorite cryptocurrencies |

---

### Administration & Governance

- **Admin Panel** — User management, content moderation, statistics dashboard
- **Scam Tracker** — Community reporting of suspicious content
- **Governance Voting** — Community decision-making
- **Audit Logs** — Complete operation records

---

### Market Data

| Feature | Description |
|---------|-------------|
| **Live Tickers** | Real-time quotes via WebSocket |
| **Multi-Exchange** | OKX + Binance unified interface |
| **Professional Charts** | Financial-grade candlestick charts |
| **Funding Rates** | Futures market data |

---

## Technical Architecture

### System Architecture

```mermaid
graph TB
    subgraph "Frontend Layer"
        UI[Web UI / TON Wallet]
        TONSDK[TON Connect SDK]
    end

    subgraph "API Layer"
        GATEWAY[FastAPI Gateway]
        WS[WebSocket Server]
        SSE[SSE Stream]
    end

    subgraph "Business Logic Layer"
        AGENTS[AI Agents - LangGraph]
        FORUM[Forum Engine]
        SOCIAL[Social Module]
        TRADING[Trading Engine]
        ADMIN[Admin Panel]
    end

    subgraph "Data Layer"
        DB[(PostgreSQL)]
        CACHE[(Redis Cache)]
        MQ[Message Queue]
    end

    subgraph "External Services"
        LLM[LLM APIs - OpenAI/Gemini/Claude]
        OKX[OKX Exchange]
        BINANCE[Binance Exchange]
        TON[TON Blockchain]
    end

    UI <--> GATEWAY
    UI <--> WS
    TONSDK <--> TON

    GATEWAY --> AGENTS
    GATEWAY --> FORUM
    GATEWAY --> SOCIAL
    GATEWAY --> TRADING
    GATEWAY --> ADMIN

    AGENTS --> LLM
    TRADING --> OKX
    TRADING --> BINANCE

    GATEWAY --> DB
    GATEWAY --> CACHE
    WS --> MQ
```

### Core Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Backend Framework** | FastAPI | High-performance async API |
| **AI Orchestration** | LangGraph | Multi-agent workflow |
| **LLM Integration** | LangChain + OpenRouter | Multi-model support |
| **Database** | PostgreSQL | Structured data storage |
| **Caching** | Redis | Market data caching |
| **Real-time Communication** | WebSocket + SSE | Bidirectional real-time push |
| **Frontend** | HTML5 + Tailwind CSS | Responsive interface |
| **Charts** | Lightweight Charts | Financial-grade charts |
| **Payments** | TON Connect SDK | Native TON payments |

### Technical Highlights

**1. LangGraph Multi-Agent System**
- Manager Agent for intelligent query classification
- Human-in-the-loop plan negotiation and modification
- Multi-step execution with specialized agents (Crypto/US Stock/TW Stock)
- Synthesized final reports with comprehensive analysis

### Autonomous Data Policy Quality Gate

The single autonomous analysis flow is protected by a dedicated test chain:

- policy-driven `discovery_lookup` / `market_lookup` routing
- membership-based tool access control
- response trace metadata (`query_type`, `resolved_market`, `policy_path`)
- Playwright E2E coverage for:
  - non-TON Wallet gate behavior
- multi-page static asset load smoke checks (with uncaught frontend runtime error guard)
- static `/static/*` asset reference integrity checks
- static shared-asset cache-busting version consistency checks
- dependency vulnerability audits for direct and locked transitive dependencies (`requirements.txt` + `requirements.lock.txt`)

Run locally:

```bash
./scripts/run_autonomous_policy_checks.sh
```

Post-deploy smoke:

```bash
API_URL=https://yourdomain.com bash scripts/post_deploy_smoke.sh
```

Weekly dependency hygiene:

```bash
bash scripts/refresh_lock_and_audit.sh
```

Reference:

- [docs/verified-mode-test-plan.md](docs/verified-mode-test-plan.md)（歷史資料）

**2. Real-time Data Architecture**
- WebSocket for bidirectional communication (messaging, notifications)
- SSE for unidirectional push (market quotes)
- Redis caching for hot data (< 100ms response)

**3. Modular Design**
- Independent API routers for each feature
- Horizontally scalable stateless architecture
- Multi-worker deployment support

---

## Deployment & Environment Variables

### Required Environment Variables

| Variable | Description | How to Generate |
|----------|-------------|-----------------|
| `DATABASE_URL` | PostgreSQL connection string | Provided by your database host |
| `JWT_SECRET_KEY` | JWT token signing key | `openssl rand -hex 32` |
| `API_KEY_ENCRYPTION_SECRET` | Encryption key for user API keys stored in database (**required in production**) | `openssl rand -hex 32` (min 32 characters) |

At least one LLM provider API key is required for AI analysis features:
- `OPENAI_API_KEY`
- `OPENROUTER_API_KEY`
- `GOOGLE_AI_API_KEY`

Copy `.env.example` to `.env` and fill in your values before starting the server.

### Production Safety Checks

The server will **refuse to start** in production if:
- `TEST_MODE=true` (authentication bypass enabled)
- `API_KEY_ENCRYPTION_SECRET` is not set or shorter than 32 characters

This prevents accidental data loss and security issues.

---

## Business Model

### Membership Tiers

| Feature | Free Member | Premium Member |
|---------|:-----------:|:----------:|
| Read Posts | ✅ | ✅ |
| View AI Analysis | ✅ | ✅ |
| Comment/Vote | ✅ 20/day | ✅ Unlimited |
| Create Posts | 💰 0.1 TON/post | ✅ Free |
| Tip Authors | ✅ | ✅ |
| Private Messaging | ❌ | ✅ |
| AI Long-term Memory | ❌ | ✅ |
| Friend System | ✅ | ✅ |
| Notification Center | ✅ | ✅ |

### Revenue Streams

```
┌─────────────────────────────────────────────┐
│              Revenue Model                   │
├─────────────────────────────────────────────┤
│  💰 Post Fees      0.1 TON/post for Free users │
│  💎 Premium Subscription USD 12/mo or USD 108/yr (TON equiv.) │
│  🔥 Future          Paid columns, AI API    │
└─────────────────────────────────────────────┘
```

### TON Connect Integration Advantages

| Aspect | Advantage |
|--------|-----------|
| **User Base** | Growing TON ecosystem user base |
| **Payment Experience** | Native SDK, one-click wallet payment |
| **Transaction Fees** | Far lower than traditional payment |
| **Ecosystem Position** | One of few finance applications on TON ecosystem |

---

## Core Team

| Member | Expertise | Core Responsibilities |
|--------|-----------|----------------------|
| **Yu-Hao Chen** | LLM & AI-Agent Architect | LLM application architecture, AI agent workflow design, Prompt Engineering |
| **Hung-Yu Lai** | Intelligent Data Retrieval | Financial data crawling, data cleaning, real-time information flow design |
| **Po-Chun Shih** | Backend & Infra Engineer | High-concurrency backend architecture, database optimization, system stability |
| **Wang-Ting Sheng** | Backend Engineer | API development, Docker containerization, cloud deployment |

### Team Advantages

- **Full-Stack Capability** — Complete coverage from AI models to backend architecture
- **Finance Background** — Familiar with cryptocurrency and traditional financial markets
- **Agile Development** — Rapid iteration, continuous value delivery

---

## Collaboration & Sponsorship

We welcome developers worldwide to exchange ideas, commission projects, or support our R&D through cryptocurrency.

**This is an independent open-source project and is not affiliated with any institution.**

### Crypto Donation

| Currency | Address |
|----------|---------|
| **BTC** | `bc1qze054pw29crex29rzus80e6gjtzmcrvd60qfkc` |
| **ETH (ERC-20)** | `0x37332CEAe1eb3AcD3a76c2dA54B8D586448F1db9` |
| **USDT (ERC-20)** | `0x37332ceae1eb3acd3a76c2da54b8d586448f1db9` |

### Contact Us

Contact team members via email, or start a discussion on GitHub.

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).

---

### Independence Statement

CryptoMind is an independent open-source project. This project is not affiliated with, endorsed by, or sponsored by any blockchain project, cryptocurrency project, or financial institution.

---

*"Collaborating to build intelligence that acts, not just talks."*

**Last Updated**: 2026-06
