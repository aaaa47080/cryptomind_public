# cryptomind-safety-kernel

**可驗證的 AI-agent 金流風險閘控規則**（TON / STON.fi Omniston）。

這是 CryptoMind 平台的「審查核心」——所有碰真錢的 swap 風險規則的單一來源。
純規則、零依賴、零網路 I/O：不查幣價、不查代幣、不碰資料庫。

## 為什麼存在

CryptoMind 讓 LLM agent 驅動 TON 上的換幣（Omniston 聚合）。操作型流程（碰資金）
不該讓 LLM 自由組合工具，而是走固定流程 + 人類同意閘。**「同意閘不可跳過」這個
聲明必須可以被驗證**——本套件就是把這份聲明變成可逐行核對的程式碼。

主平台（私有 repo）的 swap 邏輯一律 `import` 這裡，不允許重複定義閾值。
主平台 `GET /api/swap/kernel-version` 回傳的版本必須等於本 repo 的 git tag——
審查員/審計員由此比對「線上跑的規則」與「開源的規則」是同一份。

## 涵蓋的規則

| 模組 | 規則 |
|---|---|
| `risk_tiers` | price impact 色階：<1% green / 1-3% yellow / 3-5% orange（同意）/ 5-15% red（同意）/ ≥15% block（硬擋，無 expert 後門） |
| `safety_rules` | jetton 安全訊號：官方驗證（whitelist）、持有者 ≥1000、admin 權限 |
| `swap_limits` | 單筆 USD 限額（灰度期 50 USD），**fail-closed**：查不到幣價就拒絕，不放行未知金額 |
| `consent_gate` | 需要同意的等級（orange/red）+ 同意足跡的 canonical SHA-256 |

### 設計原則

- **金額不論大小都要確認**：執行 swap 必須經過使用者顯式確認（主平台 `/confirm`）。
- **限額是防 bug 後備保險**：與同意卡疊加——使用者同意也無法一次賭超過上限。
- **同意足跡不可否認**：每次 confirm 記錄 `consent_hash`（`consent_payload_hash`），
  內容是「使用者同意的事實」（quote/數量/最低收到/風險等級/價格影響/kernel 版本）
  的 canonical SHA-256。

## 如何驗證「線上 = 開源」

1. 開此 repo，切到 `v<version>` tag（例如 `v0.1.0`）。
2. 呼叫線上主平台 `GET /api/swap/kernel-version`，比對回傳的 `version`。
3. 每筆 swap 歷史（`GET /api/swap/history`）也記錄當次使用的 `kernel_version`。

## 測試

```bash
python -m pytest tests/
python -m ruff check .
```

## License

MIT — 這是信任錨點，開源讓「安全關鍵層」可以被檢視；
分析引擎與商業邏輯不在本套件內（保留在主平台私有 repo）。
