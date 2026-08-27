# CryptoMind — 用戶可配置 Agent 規則系統

> 參考專案：[ValueCell](https://github.com/ValueCell-ai/valuecell/tree/main)
> 日期：2026-05-28
> 狀態：規劃中（待 DANNY 確認後實作）

---

## 一、背景與動機

### 現狀問題

Pi Crypto Insight 的 Agent 系統 prompt 全部寫死在 YAML 檔案中（`core/agents/prompts/*.yaml`，共 9 個檔案、約 1700 行），用戶無法調整分析行為。所有用戶看到的是完全相同的分析風格、回覆格式和處理邏輯。

### ValueCell 的啟發

ValueCell 採用**兩層 prompt 架構**：

| 層級 | 控制者 | 說明 |
|------|--------|------|
| **System Prompt**（固定） | 開發者 | Agent 角色定義、行動 schema、硬性約束 |
| **Strategy Template**（用戶可編輯） | 用戶 | 交易風格、信號偏好、風控規則 |

用戶透過前端三步精靈（選模型 → 選交易所 → 編輯策略規則）建立自定義策略。策略模板存在 DB `StrategyPrompt` model，提供 CRUD API。

關鍵檔案：
- `python/valuecell/agents/prompt_strategy_agent/templates/` — 預設模板（default.txt / aggressive.txt / insane.txt）
- `python/valuecell/server/api/routers/strategy_prompts.py` — 用戶 prompt CRUD API
- `python/valuecell/server/db/models/strategy_prompt.py` — `name` + `content` 存用戶規則

### Pi 的差異

Pi 是**分析助手**不是自營交易機器人，所以用戶自定義的核心是「分析偏好」而非「交易策略」。但我們可以借用 ValueCell 的「固定底層 + 用戶可編輯上層」模式。

---

## 二、目前已完成的修改（commit `96c06be`）

### 2.1 Dead Code Cleanup

- 60 個檔案從 git tracking 移除，搬入 `REMOVE/`（commit `0f7d494`）
- `.gitignore` 已加入 `REMOVE/`

### 2.2 LLM 多 Provider 擴充

| 項目 | 變更 |
|------|------|
| `core/orm/user_api_keys_repo.py` | `SUPPORTED_PROVIDERS` 從 5 → 7（新增 deepseek、siliconflow） |
| `core/model_config.py` | 7 個 provider、25 個最新模型（2026/05 驗證） |
| `utils/user_client_factory.py` | `OPENAI_COMPATIBLE_BASE_URLS` dict 統一管理 OpenAI-compatible provider |
| `core/agents/model_router.py` | 移除成本追蹤、更新 TASK_MODEL_MAP 為最新模型 |
| `core/agents/token_tracker.py` | 移除成本估算（BYOK 模式不需要） |
| `core/agents/manager/llm.py` | 移除 `spent_usd` 參數 |

**各 Provider 模型（2026/05/28 最新）**：

| Provider | 預設 | 可選 |
|----------|------|------|
| OpenAI | `gpt-5.4-mini` | GPT-5.5 / 5.4 / 5.4-mini / 5.4-nano / 5-mini / 4.1-mini |
| Google Gemini | `gemini-3.5-flash` | 3.5 Flash / 2.5 Pro |
| Anthropic | `claude-sonnet-4-6` | Opus 4.7 / Sonnet 4.6 / Haiku 4.5 |
| Groq | `openai/gpt-oss-120b` | GPT-OSS 120B/20B、Llama 3.3/4、Qwen3、Llama 3.1 8B |
| OpenRouter | `gpt-5.4-mini` | 用戶自行輸入 |
| DeepSeek | `deepseek-v4-flash` | V4 Pro / V4 Flash |
| SiliconFlow | `deepseek-ai/DeepSeek-V4-Pro` | V4 Pro/Flash、Qwen 3.5、GLM-5.1、Gemma 4 |

### 2.3 設計決策

- **BYOK（Bring Your Own Key）**：使用者自帶 API key，平台不代付費用
- **無免費用戶**：上線後所有使用者必須連接 TON Wallet 認證
- **會員等級 ≠ 模型限制**：等級是功能面（發文、社群等），模型選擇完全開放
- **不計價**：Chat API 連接模型這件事上不計算價格

---

## 三、用戶可配置 Agent 規則 — 規劃

### 3.1 架構設計：三層漸進

```
┌──────────────────────────────────────────────────┐
│  第三層：進階規則編輯器（長期）                      │
│  - 工具使用優先順序                                │
│  - 分析流程步驟自定義                              │
│  - 回覆格式模板                                   │
├──────────────────────────────────────────────────┤
│  第二層：自定義分析規則（中期）                      │
│  - 用戶自寫分析規則文本（參考 ValueCell Template）  │
│  - 「偏好技術面 > 基本面」                         │
│  - 「只關注 BTC/ETH/SOL」                         │
│  - UserPromptTemplate DB model + CRUD API        │
├──────────────────────────────────────────────────┤
│  第一層：分析偏好設定（短期，優先實作）               │
│  - 分析風格（保守/均衡/激進）                       │
│  - 回覆詳細度（精簡/標準/詳盡）                     │
│  - 語言風格（專業術語/白話文）                      │
│  - 預設模型偏好（快速/平衡/最強）                    │
│  - UserAnalysisPreference DB model + API          │
└──────────────────────────────────────────────────┘
```

---

### 3.2 第一層：分析偏好設定（優先實作）

#### 3.2.1 新增 DB Model

檔案：`core/database/user_analysis_preference.py`

```python
class UserAnalysisPreference(Base):
    __tablename__ = "user_analysis_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.ton_address"), unique=True, nullable=False)

    # 分析風格：conservative / balanced / aggressive
    analysis_style = Column(String(20), default="balanced")

    # 回覆詳細度：concise / standard / detailed
    response_detail = Column(String(20), default="standard")

    # 語言風格：professional / casual
    language_style = Column(String(20), default="professional")

    # 預設模型偏好：fast / balanced / powerful
    model_preference = Column(String(20), default="balanced")

    # 關注市場（JSON array）：["crypto", "us_stock", "tw_stock"]
    focus_markets = Column(JSON, default=["crypto"])

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```

#### 3.2.2 新增 API 端點

檔案：`api/routers/user_preferences.py`

```
GET    /api/user/preferences          — 取得用戶偏好
PUT    /api/user/preferences          — 更新用戶偏好
GET    /api/user/preferences/options  — 取得可選項目（前端下拉用）
```

#### 3.2.3 注入 Prompt 的方式

修改 `core/agents/prompt_registry.py` 的 `render()` 方法，新增可選參數 `user_preferences`：

```python
# 在 render() 中，如果傳入 user_preferences，自動注入偏好指令
if user_preferences:
    style_map = {
        "conservative": "請以保守穩健的語氣分析，著重風險提示與下行保護。",
        "balanced": "請以客觀中立的角度分析，同時呈現多空觀點。",
        "aggressive": "請以積極進取的角度分析，著重機會辨識與上行空間。",
    }
    detail_map = {
        "concise": "回覆控制在 3-5 個要點，每點不超過兩句話。",
        "standard": "提供完整分析，包含關鍵指標與結論。",
        "detailed": "提供詳盡分析，包含所有相關數據、圖表描述、歷史比較與多情境推演。",
    }
    # 注入到 prompt 尾部
    preference_instruction = style_map.get(prefs.analysis_style, "")
    preference_instruction += "\n" + detail_map.get(prefs.response_detail, "")
```

在 `core/agents/manager/llm.py` 的 LLM 呼叫處，從 `ManagerState` 取得用戶偏好並傳入 `render()`。

#### 3.2.4 前端 UI

在用戶設定頁面新增「分析偏好」面板：

```
┌─────────────────────────────────┐
│  分析偏好設定                     │
│                                 │
│  分析風格    [保守 ▼]            │
│  回覆詳細度  [標準 ▼]            │
│  語言風格    [專業 ▼]            │
│  模型偏好    [平衡 ▼]            │
│  關注市場    [✓加密 ✗美股 ✗台股]  │
│                                 │
│         [儲存設定]               │
└─────────────────────────────────┘
```

#### 3.2.5 受影響檔案清單

| 檔案 | 變更類型 | 說明 |
|------|----------|------|
| `core/database/user_analysis_preference.py` | 新增 | DB model |
| `alembic/versions/xxx_add_user_preferences.py` | 新增 | Migration |
| `core/orm/user_preference_repo.py` | 新增 | Repository |
| `api/routers/user_preferences.py` | 新增 | API 端點 |
| `api/main.py` | 修改 | 註冊新 router |
| `core/agents/prompt_registry.py` | 修改 | render() 支援偏好注入 |
| `core/agents/manager/_main.py` | 修改 | ManagerState 新增 preferences 欄位 |
| `core/agents/manager/llm.py` | 修改 | LLM 呼叫時傳入偏好 |
| `core/agents/model_router.py` | 修改 | resolve_model() 讀取 model_preference |
| `web/js/` 相關設定頁面 | 修改 | 前端 UI |

---

### 3.3 第二層：自定義分析規則（中期）

#### 3.3.1 概念

參考 ValueCell 的 `StrategyPrompt` 模式，讓用戶可以撰寫自由文本的分析規則。這些規則會在 Manager Agent 的 `plan` 和 `synthesize` 階段注入 prompt。

用戶寫的規則範例：

```
我偏好技術面分析大於基本面，請優先使用技術指標工具。
我關注的幣種是 BTC、ETH、SOL，其他幣種除非特別提及否則不需要分析。
風險提示請用紅色警告格式，並且每次都要列出支撐/壓力位。
```

#### 3.3.2 新增 DB Model

檔案：`core/database/user_prompt_template.py`

```python
class UserPromptTemplate(Base):
    __tablename__ = "user_prompt_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.ton_address"), nullable=False)
    name = Column(String(100), nullable=False)         # 用戶自訂名稱
    content = Column(Text, nullable=False)              # 規則文本
    is_active = Column(Boolean, default=False)          # 是否啟用
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```

#### 3.3.3 API 端點

```
GET    /api/user/prompt-templates          — 列出用戶所有模板
POST   /api/user/prompt-templates          — 建立新模板
PUT    /api/user/prompt-templates/{id}     — 更新模板
DELETE /api/user/prompt-templates/{id}     — 刪除模板
PUT    /api/user/prompt-templates/{id}/activate — 設為啟用
```

#### 3.3.4 注入方式

在 Manager Agent 的 `intent_understanding` prompt 尾部追加：

```
## 用戶自定義分析規則
{user_template_content}
請在分析過程中遵循以上規則。
```

#### 3.3.5 預設模板（供新用戶選擇）

參考 ValueCell 的 `default.txt` / `aggressive.txt`，提供幾個預設：

- **保守型**：著重風險提示、支撐位分析、保守估值
- **均衡型**：多空並陳、技術面 + 基本面並重
- **激進型**：著重突破信號、成長空間、新興題材

---

### 3.4 第三層：進階規則編輯器（長期）

#### 3.4.1 概念

讓進階用戶可以定義更結構化的規則，包含：

1. **工具使用優先順序** — 例如「先看技術面，再看新聞」
2. **分析流程步驟** — 自定義 Manager Agent 的 task 拆解邏輯
3. **回覆格式模板** — 自定義輸出格式（表格、列表、圖表描述等）

#### 3.4.2 實作方式

採用 JSON Schema 定義規則結構，前端用表單編輯器而非自由文本：

```json
{
  "tool_priority": ["technical_analysis", "price_data", "news", "fundamentals"],
  "analysis_steps": [
    {"step": "price_check", "required": true},
    {"step": "technical_indicators", "required": true},
    {"step": "news_sentiment", "required": false},
    {"step": "risk_assessment", "required": true}
  ],
  "output_format": {
    "sections": ["summary", "technical", "fundamentals", "risk", "conclusion"],
    "max_length": "detailed"
  }
}
```

#### 3.4.3 這層暫不實作

等第一、二層驗證用戶需求後再評估。

---

## 四、analysis_policy.json 需要重新評估

> **已廢棄（2026-07）**：以下 `analysis_mode`／`tier_modes` 內容是舊版規劃，現行產品採單一自治分析流程；工具權限由 membership tier 的 `ToolAccessResolver` 控制。本節僅保留決策歷史，不能作為實作依據。

目前 `config/analysis_policy.json` 仍有 `tier_modes` 的 free/premium 區分：

```json
"tier_modes": {
    "free": { "allowed_modes": ["quick"], "default_mode": "quick" },
    "premium": { "allowed_modes": ["quick", "verified", "research"], "default_mode": "verified" }
}
```

但 DANNY 已確認：
- **沒有免費用戶** — 上線後必須連接 TON Wallet
- **會員等級跟模型無關** — 等級是功能面的事

**建議**：將 `tier_modes` 改為功能導向（例如「基礎會員」和「進階會員」），或直接移除 free tier，讓所有用戶都能使用 verified/research 模式。這需要 DANNY 確認進階會員的功能定義。

---

## 五、實作優先順序

| 階段 | 項目 | 預估工時 | 風險 |
|------|------|----------|------|
| ✅ 已完成 | Dead code cleanup | — | — |
| ✅ 已完成 | 7 Provider + 25 模型擴充 | — | — |
| 🔜 Phase 1 | 分析偏好 DB + API + prompt 注入 | 1-2 天 | 低 |
| 🔜 Phase 1 | 前端偏好設定 UI | 1 天 | 低 |
| 📋 Phase 2 | UserPromptTemplate DB + CRUD API | 1-2 天 | 中 |
| 📋 Phase 2 | 預設模板 + 前端編輯器 | 2-3 天 | 中 |
| 📋 Phase 3 | 進階規則編輯器 | 3-5 天 | 高 |
| ⚠️ 待確認 | analysis_policy.json tier 重新設計 | 0.5 天 | 需 DANNY 確認 |

---

## 六、技術架構圖

```
用戶 UI 設定
    │
    ├─ 分析偏好（風格/詳細度/語言/模型/市場）
    │      ↓
    │   UserAnalysisPreference (DB)
    │      ↓
    │   /api/user/preferences (CRUD)
    │      ↓
    │   prompt_registry.render(user_preferences=...)
    │      ↓
    │   Manager Agent prompt 注入偏好指令
    │
    └─ 自定義規則（自由文本模板）
           ↓
        UserPromptTemplate (DB)
           ↓
        /api/user/prompt-templates (CRUD)
           ↓
        Manager Agent intent_understanding prompt 注入規則
```

---

## 七、ValueCell 值得參考的其他模式

| 模式 | ValueCell 做法 | Pi 適用性 | 備註 |
|------|---------------|-----------|------|
| 用戶自定義策略模板 | StrategyPrompt CRUD | ✅ 適用 | 第二層可直接參考 |
| 固定 System Prompt + 用戶 Template 兩層 | system_prompt.py + template.txt | ✅ 適用 | 保持底層穩定，上層可配置 |
| Agent YAML 配置 | configs/agents/*.yaml | ⚠️ 部分適用 | Pi 已有類似架構（analysis_policy.json） |
| ModelProvider 抽象工廠 | CCXT exchange adapter | ⚠️ 長期參考 | Pi 目前用 dict 映射已足夠 |
| 前端三步精靈 | Model → Exchange → Strategy | ✅ 適用 | 可簡化為 Model → Preferences |

---

*文件維護者：DANNY + AI Agent*
*下次更新：Phase 1 實作完成後*
