# BotFather 設定逐項清單(送審前)

> 在 Telegram 跟 **@BotFather** 對話,逐項設定。審核員會點 bot 看這些。
> Bot:`@CryptoMind_TON_BOT`

## A. 文案 / 外觀
| 指令 | 填什麼 |
|------|--------|
| `/setname` | `CryptoMind` |
| `/setdescription` | （顯示在空白聊天室的介紹,英文)貼:`CryptoMind — your AI market analyst on TON. Ask anything about crypto, US & Taiwan stocks: live charts, screener, price alerts. TON Connect login + TON payments.` |
| `/setabouttext` | （個人檔案的短介紹,≤120 字)貼:`AI analysis for crypto, US & TW stocks. Live charts, screener, alerts. Built on TON.` |
| `/setuserpic` | 上傳 `store-assets/tapps/icon_512.png`(或 icon_1024) |
| `/setcommands` | 貼下方指令清單 ↓ |

`/setcommands` 內容(程式已註冊,但 BotFather 這份是備援/顯示用):
```
start - Open CryptoMind
sessions - Pick / switch conversation
new - Start a new conversation
link - Bind platform account
help - Show help
```

## B. Mini App 進入點(關鍵)
| 項目 | 設定 |
|------|------|
| 具名 Mini App `cmind` | 已用 `/newapp` 建立 ✅,連結 `t.me/CryptoMind_TON_BOT/cmind` |
| Menu Button | Bot Settings → Menu Button → **設為 Web App** → URL `https://cryptomind-ton.zeabur.app`(程式啟動時也會自動設) |

> ⚠️ Menu Button URL 必須是 `-ton`(`cryptomind.zeabur.app` 無 -ton 是舊 Pi 版,別填)。

## C. 驗證(設定完自己點一次)
- [ ] `/start` → 出現「🚀 Open CryptoMind」按鈕,點了以 Mini App 開啟(非內建瀏覽器)
- [ ] 左下 Menu 鈕 → 開到 TON 版(「Connect TON Wallet」/ 自動 Telegram 登入),非 Pi 版
- [ ] 進 App 後自動登入、可正常使用各分頁
