"""Lightweight i18n for the Telegram bot.

The bot is a standalone service with no access to the web frontend's
i18next bundles, so it keeps its own translation dict here. Keys mirror
the error codes returned by the API (e.g. ``NO_API_KEY``) plus bot-only
strings (welcome, help, etc.).

Language resolution:
1. ``language`` arg passed to ``t()``
2. Fallback: ``DEFAULT_LANGUAGE``
"""

from __future__ import annotations

from typing import Optional

DEFAULT_LANGUAGE = "zh-TW"

MESSAGES: dict[str, dict[str, str]] = {
    "zh-TW": {
        # /start
        "welcome": (
            "👋 歡迎來到 CryptoMind Bot！\n\n"
            "我可以幫您分析加密貨幣、追蹤行情，即時回答您的問題。\n\n"
            "🔗 第一次使用？請先到網站取得連結 Token，"
            "然後輸入 /link <token> 來綁定您的帳號。\n\n"
            "📌 使用說明：\n"
            "  /link <token> — 綁定平台帳號\n"
            "  /check <地址> — 轉帳前地址健診\n"
            "  /sessions — 選擇 / 切換對話\n"
            "  /new — 開新對話\n"
            "  /unlink — 解除帳號綁定\n"
            "  /help — 顯示所有指令"
        ),
        # Mini App launch button (web_app)
        "open_app": "🚀 開啟 CryptoMind",
        # /check 地址健診（design 2026-08-18）
        "check_usage": "🔎 用法：/check <地址>\n貼上 TON（EQ/UQ…）或 EVM（0x…）地址，轉帳前先查一下。",
        "check_high_risk": "🚨 高風險 — 建議不要轉帳",
        "check_caution": "⚠️ 留意 — 資訊不完整或有黃旗",
        "check_no_red_flags": "✅ 未發現紅旗（非保證安全）",
        "check_invalid_address": "❌ 地址格式不正確（需 TON EQ/UQ… 或 EVM 0x…）",
        "check_rate_limited": "⏳ 查詢太頻繁，請稍後再試",
        "check_failed": "❌ 健診暫時無法使用，請稍後再試",
        "check_footer": "判定由社群舉報＋GoPlus＋TonAPI 即時合成，僅供參考。\n🌐 完整報告：/scam-tracker/",
        # /help
        "help": (
            "📖 CryptoMind Bot 指令說明\n\n"
            "  /start — 顯示歡迎訊息\n"
            "  /link <token> — 綁定您的 CryptoMind 帳號\n"
            "  /sessions — 列出並切換對話（與網頁端共用記錄）\n"
            "  /new — 切換到全新的 Telegram 對話\n"
            "  /unlink — 解除帳號綁定\n"
            "  /help — 顯示本說明\n\n"
            "直接傳送訊息給我，我會轉交給 AI 分析師回覆！"
        ),
        # /sessions & /new
        "sessions_header": "💬 選擇要繼續的對話（✅ 為目前對話）：",
        "sessions_empty": "目前沒有對話記錄。直接傳訊息給我即可開始新對話。",
        "sessions_failed": "⚠️ 無法載入對話列表，請稍後再試。",
        "sessions_default_label": "🆕 Telegram 預設對話",
        "session_switched": "✅ 已切換到：{title}\n\n之後的訊息都會接續這個對話。",
        "session_new_done": "✅ 已開新對話。之後的訊息會記在全新的 Telegram 對話裡。",
        "SESSION_NOT_FOUND": "找不到該對話，可能已被刪除，請用 /sessions 重新選擇。",
        # /link
        "link_missing_token": (
            "❌ 請提供連結 Token。\n"
            "格式：/link <您的token>\n\n"
            "請到 CryptoMind 網站取得 Token。"
        ),
        "link_success": "✅ 綁定成功！\n\n已將 Telegram 帳號綁定至：@{username}\n\n現在可以直接傳送訊息給我，我會為您分析市場！",
        "link_failed": "❌ 綁定失敗：{detail}",
        # /unlink
        "unlink_redirect": (
            "ℹ️ 解除綁定需在網站操作。\n\n"
            "請前往 CryptoMind 網站的「個人設定」頁面，"
            "找到 Telegram 綁定設定並解除。"
        ),
        # chat errors (mapped from API error codes)
        "NOT_BOUND": "⚠️ 請先使用 /link <token> 指令綁定您的帳號。",
        "RATE_LIMITED": "⚠️ 操作太頻繁了，請稍後再試。",
        "ALREADY_LINKED": "此 Telegram 帳號已經綁定過了，無法重複綁定。",
        "INVALID_TOKEN": "連結 Token 無效或已過期，請在網站重新取得。",
        "USER_NOT_ACTIVE": "您的帳號狀態異常，請聯繫客服。",
        "NO_API_KEY": (
            "⚠️ 您尚未設定 LLM API Key。\n\n"
            "請先到 CryptoMind 網站的「設定」頁面，配置任一 API Key：\n"
            "  • OpenAI\n  • OpenRouter\n  • Google AI\n\n"
            "設定完成後即可使用 AI 分析功能。"
        ),
        "INVALID_API_KEY": "⚠️ API Key 無效，請到網站設定頁面檢查您的 API Key。",
        "ANALYSIS_FAILED": "⚠️ 分析失敗，請稍後再試。",
        # generic
        "timeout": "⏳ 回覆時間過長，伺服器忙碌中，請稍後再試。",
        "link_timeout": "⚠️ 連線逾時，請稍後重試。",
        "unknown_error": "⚠️ 發生未知錯誤，請稍後重試或聯繫客服。",
        "empty_response": "（無法產生回覆，請稍後再試。）",
    },
    "en": {
        "welcome": (
            "👋 Welcome to CryptoMind Bot!\n\n"
            "I can help you analyze crypto, track markets, and answer your questions in real time.\n\n"
            "🔗 First time? Get a link token from the website, "
            "then send /link <token> to bind your account.\n\n"
            "📌 Commands:\n"
            "  /link <token> — Bind platform account\n"
            "  /sessions — Pick / switch conversation\n"
            "  /new — Start a new conversation\n"
            "  /check <address> — Address safety check before transferring\n"
            "  /unlink — Unbind account\n"
            "  /help — Show all commands"
        ),
        "open_app": "🚀 Open CryptoMind",
        # /check address safety check (design 2026-08-18)
        "check_usage": "🔎 Usage: /check <address>\nPaste a TON (EQ/UQ…) or EVM (0x…) address — check before you transfer.",
        "check_high_risk": "🚨 High risk — do not transfer",
        "check_caution": "⚠️ Caution — incomplete info or yellow flags",
        "check_no_red_flags": "✅ No red flags found (not a guarantee)",
        "check_invalid_address": "❌ Invalid address format (expect TON EQ/UQ… or EVM 0x…)",
        "check_rate_limited": "⏳ Too many requests, please retry later",
        "check_failed": "❌ Check temporarily unavailable, please retry later",
        "check_footer": "Verdict combines community reports + GoPlus + TonAPI live. Reference only.\n🌐 Full report: /scam-tracker/",
        "help": (
            "📖 CryptoMind Bot Commands\n\n"
            "  /start — Show welcome message\n"
            "  /link <token> — Bind your CryptoMind account\n"
            "  /sessions — List & switch conversations (shared with the web)\n"
            "  /new — Switch to a fresh Telegram conversation\n"
            "  /unlink — Unbind account\n"
            "  /help — Show this help\n\n"
            "Send me a message and I'll forward it to the AI analyst!"
        ),
        "sessions_header": "💬 Pick a conversation to continue (✅ = current):",
        "sessions_empty": "No conversations yet. Just send me a message to start one.",
        "sessions_failed": "⚠️ Couldn't load your conversations. Please try again later.",
        "sessions_default_label": "🆕 Default Telegram chat",
        "session_switched": "✅ Switched to: {title}\n\nYour next messages will continue this conversation.",
        "session_new_done": "✅ New conversation started. Your next messages go into a fresh Telegram chat.",
        "SESSION_NOT_FOUND": "Conversation not found — it may have been deleted. Use /sessions to pick again.",
        "link_missing_token": (
            "❌ Please provide a link token.\n"
            "Format: /link <your-token>\n\n"
            "Get your token from the CryptoMind website."
        ),
        "link_success": "✅ Bound successfully!\n\nTelegram account linked to: @{username}\n\nSend me a message and I'll analyze the market for you!",
        "link_failed": "❌ Binding failed: {detail}",
        "unlink_redirect": (
            "ℹ️ Unbinding must be done on the website.\n\n"
            "Go to the CryptoMind website → Account Settings → "
            "Telegram binding settings to unbind."
        ),
        "NOT_BOUND": "⚠️ Please bind your account first using /link <token>.",
        "RATE_LIMITED": "⚠️ Too many requests, please try again later.",
        "ALREADY_LINKED": "This Telegram account is already linked and cannot be bound again.",
        "INVALID_TOKEN": "Link token is invalid or expired. Please get a new one from the website.",
        "USER_NOT_ACTIVE": "Your account status is abnormal. Please contact support.",
        "NO_API_KEY": (
            "⚠️ You haven't configured an LLM API Key.\n\n"
            "Please go to the CryptoMind website → Settings and set up any API Key:\n"
            "  • OpenAI\n  • OpenRouter\n  • Google AI\n\n"
            "AI analysis will be available once configured."
        ),
        "INVALID_API_KEY": "⚠️ Invalid API Key. Please check your API Key in the website settings.",
        "ANALYSIS_FAILED": "⚠️ Analysis failed. Please try again later.",
        "timeout": "⏳ Response is taking too long. The server is busy — please try again later.",
        "link_timeout": "⚠️ Connection timed out. Please try again.",
        "unknown_error": "⚠️ An unknown error occurred. Please try again or contact support.",
        "empty_response": "(Unable to generate a response. Please try again later.)",
    },
}


def t(key: str, language: Optional[str] = None, **kwargs) -> str:
    """Look up a translated message.

    Falls back to ``DEFAULT_LANGUAGE`` if ``language`` is missing or unknown,
    then to the raw ``key`` if the key itself is missing.
    """
    lang = language if language and language in MESSAGES else DEFAULT_LANGUAGE
    text = MESSAGES[lang].get(key, MESSAGES[DEFAULT_LANGUAGE].get(key, key))
    return text.format(**kwargs) if kwargs else text
