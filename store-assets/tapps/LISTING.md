# CryptoMind — Telegram Apps Center 上架素材

> 直接複製貼上到 tApps Moderation Bot 的提交表單。英文為主(審核員看英文)。

---

## App name
```
CryptoMind
```

## Tagline (一句話特色 — 任選一個)
```
Your AI market analyst on TON — crypto, US & TW stocks
```
備選:
```
Ask AI anything about crypto and stocks, right in Telegram
```

## Category
建議選 **Finance** 或 **Analytics**(若無則 **Other**)。

## Short description (~1 行)
```
AI-powered analysis for crypto, US and Taiwan stocks — live charts, market screener, and price alerts, with TON Connect login and TON payments.
```

## Long description (口語、像在跟人介紹)
```
CryptoMind is your AI market analyst, built right into Telegram.

Ask the AI anything — "How's BTC looking?", "Analyze TSMC", "ETH vs SOL" — and get a clear, real-time read on the market. No spreadsheets, no jargon walls.

What you get:
• AI analysis powered by OpenAI, Google Gemini or OpenRouter (bring your own key, encrypted and stored safely)
• Live crypto markets with a smart screener — top performers, gainers, losers, and an AI "Pulse" view
• Pro real-time K-line charts with OHLCV, multiple timeframes, zoom and crosshair
• Not just crypto — US stocks and Taiwan stocks too
• Price alerts so you never miss a move
• One chat, everywhere — your conversations sync between the web app and Telegram

Built on TON: sign in with TON Connect, and unlock premium with TON payments. TON-only, no other chains.
```

## TON 整合(審核會問)
- 登入:TON Connect
- 付款:TON(premium / 發文 / 打賞),**TON-only,無其他鏈**
- Manifest:`https://cryptomind-ton.zeabur.app/tonconnect-manifest.json`(含 termsOfUse + privacyPolicy)

## Bot
- Username:`@CryptoMind_TON_BOT`
- `/start` 預設**英文**回覆(已修,僅 zh 客戶端回中文)— tApps 硬性檢查項 ✅

## Icon
- 用 `store-assets/tapps/icon_512.png`(512×512)或 `icon_1024.png`。
- ✅ 從 `REMOVE/icon/title_icon.png`(2048×2048 原檔)縮製,銳利、品牌正確(CryptoMind 大腦 logo,非 Pi),可直接送審。

---

## 截圖計畫(6 格,要做得像廣告 — 上方壓一句標語)

✅ **6 張已自動產出**(900×1600、英文版)在 `store-assets/tapps/screenshots/`,可直接上傳。
建議上傳時每張上方壓一句行銷標語:

| # | 檔案 | 畫面 | 建議標語(英文) |
|---|------|------|----------------|
| 1 | `1_chat.png` | 聊天歡迎頁 | `Ask AI anything about the markets` |
| 2 | `2_crypto_market.png` | Crypto 市場列表 | `Live crypto screener — top movers at a glance` |
| 3 | `3_chart.png` | BTC K 線圖 | `Pro real-time charts, right in Telegram` |
| 4 | `4_twstock.png` | 台股 watchlist | `Track TW stocks — TSMC, Hon Hai & more` |
| 5 | `5_usstock.png` | 美股 watchlist | `US stocks too — Apple, Microsoft, Alphabet` |
| 6 | `6_settings.png` | 設定 / TON 錢包 | `TON Connect login + premium` |

> 註:AI Pulse 畫面需即時 AI 運算,截圖會空白,故以美股頁替代(同時展現「不只加密貨幣」的廣度)。
> 截圖已是 900×1600,免再跑 resize。若日後要處理手機自拍的原圖,仍可用
> `store-assets/tapps/resize_screenshots.py`(raw/ → out/)。

---

## 送審前最終 checklist

- [x] Terms of Use + Privacy Policy(`/legal/*`)
- [x] TON-only + TON Connect
- [x] Bot `/start` 預設英文
- [x] App 可運作、無破版、無 console error(已 QA,#95–#102)
- [x] Icon ≥512 正方、高解析(從 2048 原檔縮製)
- [x] 6 張截圖 900×1600(英文,在 `screenshots/`)
- [ ] data bot 顯示近期活動(證明有人用)— tApps 會看
