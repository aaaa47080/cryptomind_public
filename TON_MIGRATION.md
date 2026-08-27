# TON 版遷移說明（Web DApp via TON Connect）

本 repo（`stock_agent_ton`）是從 Pi 版 fork 出來、改用 **TON Connect** 做認證與付款的 Web DApp。
論壇 / 好友 / AI 分析 / 後端邏輯完全沿用，只替換了「認證」與「付款」兩個平台層。

> **2026-06 更新：Pi Network 已完全移除。** auth（`pi-auth.js`、`/api/user/pi-sync`）、
> payment（`Pi.createPayment`、`/api/user/payment/approve|complete`、Pi 三階段流程）、
> DB 欄位（`pi_uid`/`pi_username`）、Pi 查價工具（`pi_tools.py`）、Pi 地址驗證器（`pi_address.py`）、
> 所有 HTML 的 `sdk.minepi.com/pi-sdk.js`、CSP/CORS 的 minepi.com 白名單、Pi 專屬 scripts/skills/tests
> 全數清除。TON Connect 是唯一的認證與付款管道。

## 改了什麼

| 層 | Pi 版 | TON 版 |
|----|-------|--------|
| 認證 | Pi SDK `Pi.authenticate` | TON Connect `ton_proof`（ed25519 驗簽） |
| 付款 | `Pi.createPayment` | TON Connect `sendTransaction`（轉帳到收款錢包 + 唯一 comment） |
| 後端驗證 | Pi Server API | toncenter API（驗鏈上交易） |
| 部署 | Pi Browser only | 任何瀏覽器 |

### 新增 / 修改檔案
- `api/ton_verification.py` — ton_proof 驗簽 + 訂單綁定 + 鏈上付款驗證（**核心**）
- `api/routers/user.py` — `GET /api/user/ton-proof-payload`、`POST /api/user/ton-login`
- `api/routers/premium.py` — `POST /api/premium/ton-order`、`/upgrade` 新增 TON 路徑、`/pricing` 加 TON 報價
- `api_server.py` — `GET /tonconnect-manifest.json`
- `core/config.py` — TON 網路 / 收款地址 / 價格設定
- `web/js/ton-auth.js` — TON Connect 初始化 + 登入（取代 `pi-auth.js`）
- `web/js/premium.js` — TON 付款流程
- `web/index.html` — 載入 TON Connect UI + TonWeb，登入按鈕改 TON

## 部署到 Zeabur

> **建議開「新的 Zeabur service」**，不要覆蓋現有的 `cryptomind.zeabur.app`（那是 Pi 版，覆蓋會讓 Pi 版下線）。
> 新 service 會拿到自己的網址，例如 `cryptomind-ton.zeabur.app`。

### 必設環境變數

```bash
# --- TON ---
TON_NETWORK=testnet                      # 先 testnet 驗證；上線改 mainnet
TON_RECEIVING_ADDRESS_TESTNET=0QDvjDhEZ128EktbSBrK4CWrw1xTTbx4ojlZ-rF2OOS2HxtR
TON_RECEIVING_ADDRESS_MAINNET=UQDvjDhEZ128EktbSBrK4CWrw1xTTbx4ojlZ-rF2OOS2H6Db
TON_MANIFEST_URL=https://<你的新網址>     # 必須是部署後的 HTTPS 網址
TONCENTER_API_KEY=                       # 選填，建議去 toncenter.com 申請避免限流
# TON 價格（單位 TON，後端防篡改）
TON_PRICE_PREMIUM_MONTHLY=1.0
TON_PRICE_PREMIUM_YEARLY=10.0

# --- 既有必設（沿用 Pi 版）---
DATABASE_URL=postgresql://...
JWT_SECRET_KEY=<openssl rand -hex 32>
API_KEY_ENCRYPTION_SECRET=<openssl rand -hex 32>
# ...其餘 LLM / SMTP 等照 .env.example
```

> ⚠️ 不要從 Pi 版直接複製 `.env`。用 `.env.example` 重新填，TON 版該有自己的金鑰。

### 上線切 mainnet 時只要改
1. `TON_NETWORK=mainnet`
2. （可選，強化）`TON_PROOF_REQUIRE_ONCHAIN_PUBKEY=true` — 綁定錢包鏈上公鑰

## 測試網付款驗證流程（最後一哩，需人工）

程式已就緒，要實際確認「可以支付」需要一個有測試幣的錢包點一次付款：

1. **裝 Tonkeeper** → 設定切到 **Testnet**（同一組助記詞會顯示 `0Q...` 測試地址）
2. **領測試幣**：Telegram 搜 `@testgiver_ton_bot`，貼上你的 testnet 地址，領 ~5 測試 TON
3. **打開部署好的網站** → Connect TON Wallet（掃碼/連 Tonkeeper）→ 進 Premium → 升級 →
   錢包彈窗確認付款 → 等數秒鏈上確認 → 會員升級成功

後端會透過 toncenter testnet 掃收款地址、比對金額與 comment、防重複使用。

## 驗證狀態（本地）
- ✅ `api/ton_verification.py` 單元測試 13/13 通過（驗簽、nonce、訂單綁定、付款比對）
- ✅ 所有後端檔案編譯通過、前端 JS 語法通過、i18n JSON 有效
- ⏳ 完整 server boot + 真實 testnet 付款 → 需在 Zeabur（有 Postgres）+ 上述人工點擊完成
