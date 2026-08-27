"""Telegram Bot Service — aiogram3-based bot that calls the CryptoMind API."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from bot.i18n import DEFAULT_LANGUAGE, MESSAGES, t

__version__ = "1.2.0"

log = logging.getLogger("bot.telegram_bot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

_TG_MESSAGE_LIMIT = 4096
# Callback-data prefix for session selection. callback_data is capped at
# 64 bytes; "tgsess:" (7) + a UUID4 (36) fits comfortably. An empty id
# after the prefix means "switch back to the default Telegram session".
_SESSION_CB_PREFIX = "tgsess:"
_SESSION_BTN_MAXLEN = 40  # keep inline button labels readable


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class BotConfig:
    token: str
    api_base_url: str
    bot_secret: str
    mode: str
    webhook_host: str
    webhook_path: str
    webapp_url: str

    @classmethod
    def from_env(cls) -> "BotConfig":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
        # Public HTTPS URL of the TON Mini App. Opening this via a web_app
        # button / menu button is what gives the page a real Telegram context
        # (platform=android/ios, initData populated).
        # IMPORTANT: this MUST be the TON deployment "cryptomind-ton.zeabur.app".
        # Do NOT fall back to TON_MANIFEST_URL — on Zeabur that may still point
        # at the OLD Pi deployment "cryptomind.zeabur.app", which would open the
        # retired Pi version ("連接 Pi 錢包").
        webapp_url = (
            os.getenv("TELEGRAM_WEBAPP_URL") or "https://cryptomind-ton.zeabur.app"
        ).rstrip("/")
        return cls(
            token=token,
            api_base_url=os.getenv("API_BASE_URL", "http://localhost:8080").rstrip("/"),
            bot_secret=os.getenv("BOT_INTERNAL_SECRET", ""),
            mode=os.getenv("TELEGRAM_BOT_MODE", "polling").lower(),
            webhook_host=os.getenv("TELEGRAM_WEBHOOK_HOST", "").rstrip("/"),
            webhook_path=os.getenv("TELEGRAM_WEBHOOK_PATH", "/bot/webhook"),
            webapp_url=webapp_url,
        )


# ---------------------------------------------------------------------------
# API Error
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _user_lang(message: Message) -> str:
    """Derive a supported language code from the Telegram user's profile."""
    lc = (message.from_user.language_code or "").lower() if message.from_user else ""
    if lc.startswith("zh"):
        return "zh-TW"
    # Default to English when the language is non-Chinese OR unknown/empty.
    # Telegram Apps Center requires the bot to reply to /start in English by
    # default; only explicit zh clients get Chinese.
    return "en"


def _detail_to_code(exc: httpx.HTTPStatusError) -> str:
    """Extract the API error code from an HTTPStatusError response."""
    try:
        data = exc.response.json()
        detail = data.get("detail", "")
        if isinstance(detail, str) and detail in MESSAGES["zh-TW"]:
            return detail
        return detail if isinstance(detail, str) else str(exc)
    except Exception:
        return str(exc)


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------


class ApiClient:
    """Calls CryptoMind bot-facing endpoints with X-Bot-Secret auth."""

    # 150s：複雜分析會跑多輪 LLM(意圖→多工具→彙整→反思→合成)，60s 常不夠用，
    # 會在伺服器仍在運算時就被 bot 端判「回覆時間過長」。設在 gunicorn timeout(180)
    # 之下、留網路餘裕。verify-link/sessions 很快，不受此上限影響。
    def __init__(self, base_url: str, bot_secret: str, timeout: float = 150.0):
        self.base_url = base_url
        self.bot_secret = bot_secret
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"X-Bot-Secret": self.bot_secret} if self.bot_secret else {}

    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers(),
            )
            return resp

    async def _get(self, path: str) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
            )
            return resp

    async def check_address(self, address: str) -> dict:
        """地址健診（公開端點；設計 2026-08-18）。422 → INVALID_ADDRESS。"""
        from urllib.parse import quote

        resp = await self._get(
            "/api/scam-tracker/reports/check?address=" + quote(address, safe="")
        )
        if resp.status_code == 422:
            raise ApiError("INVALID_ADDRESS", 422)
        if resp.status_code == 429:
            raise ApiError("RATE_LIMITED", 429)
        resp.raise_for_status()
        return resp.json()

    async def verify_link(
        self,
        token: str,
        telegram_id: int,
        username: Optional[str],
        first_name: Optional[str],
    ) -> dict:
        resp = await self._post(
            "/api/telegram/verify-link",
            {
                "token": token,
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
            },
        )
        if resp.status_code == 409:
            raise ApiError("ALREADY_LINKED", 409)
        if resp.status_code == 400:
            raise ApiError("INVALID_TOKEN", 400)
        if resp.status_code == 403:
            raise ApiError("USER_NOT_ACTIVE", 403)
        resp.raise_for_status()
        return resp.json()

    async def chat(
        self, telegram_id: int, message: str, language: str = "zh-TW"
    ) -> dict:
        resp = await self._post(
            "/api/telegram/chat",
            {
                "telegram_id": telegram_id,
                "message": message,
                "language": language,
            },
        )
        if resp.status_code == 403:
            raise ApiError("NOT_BOUND", 403)
        if resp.status_code == 429:
            raise ApiError("RATE_LIMITED", 429)
        resp.raise_for_status()
        return resp.json()

    async def list_sessions(self, telegram_id: int) -> dict:
        resp = await self._post("/api/telegram/sessions", {"telegram_id": telegram_id})
        if resp.status_code == 403:
            raise ApiError("NOT_BOUND", 403)
        if resp.status_code == 429:
            raise ApiError("RATE_LIMITED", 429)
        resp.raise_for_status()
        return resp.json()

    async def use_session(self, telegram_id: int, session_id: Optional[str]) -> dict:
        resp = await self._post(
            "/api/telegram/use-session",
            {"telegram_id": telegram_id, "session_id": session_id},
        )
        if resp.status_code == 403:
            raise ApiError("NOT_BOUND", 403)
        if resp.status_code == 404:
            raise ApiError("SESSION_NOT_FOUND", 404)
        if resp.status_code == 429:
            raise ApiError("RATE_LIMITED", 429)
        resp.raise_for_status()
        return resp.json()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _send_long_text(bot: Bot, chat_id: int, text: str) -> None:
    """Split and send a message that exceeds Telegram's 4096-char limit."""
    if len(text) <= _TG_MESSAGE_LIMIT:
        await bot.send_message(chat_id=chat_id, text=text)
        return
    lines = text.split("\n")
    chunk = ""
    for line in lines:
        test = (chunk + "\n" + line).strip()
        if len(test) <= _TG_MESSAGE_LIMIT:
            chunk = test
        else:
            if chunk:
                await bot.send_message(chat_id=chat_id, text=chunk)
                await asyncio.sleep(0.1)
            while len(line) > _TG_MESSAGE_LIMIT:
                await bot.send_message(chat_id=chat_id, text=line[:_TG_MESSAGE_LIMIT])
                await asyncio.sleep(0.1)
                line = line[_TG_MESSAGE_LIMIT:]
            chunk = line
    if chunk:
        await bot.send_message(chat_id=chat_id, text=chunk)


def _build_sessions_keyboard(data: dict, lang: str) -> InlineKeyboardMarkup:
    """Render the session list as one inline button per row.

    Always includes a row for the default Telegram session so users can
    return to it without /new.
    """
    rows: list[list[InlineKeyboardButton]] = []
    active_id = data.get("active_session_id")

    for s in data.get("sessions", []):
        # 預設 tg session 由下方獨立按鈕呈現，避免重複。
        if str(s.get("id", "")).startswith("tg:"):
            continue
        title = (s.get("title") or "New Chat").strip()
        if len(title) > _SESSION_BTN_MAXLEN:
            title = title[: _SESSION_BTN_MAXLEN - 1] + "…"
        label = ("✅ " if s.get("is_active") else "💬 ") + title
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=_SESSION_CB_PREFIX + str(s["id"]),
                )
            ]
        )

    default_active = not active_id or str(active_id).startswith("tg:")
    default_label = ("✅ " if default_active else "") + t(
        "sessions_default_label", lang
    )
    rows.append(
        [InlineKeyboardButton(text=default_label, callback_data=_SESSION_CB_PREFIX)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def create_handlers(api: ApiClient, webapp_url: str) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def cmd_start(message: Message) -> None:
        lang = _user_lang(message)
        # A web_app button launches the page AS a Mini App (real platform +
        # initData), unlike a plain URL button which only opens the in-app
        # browser (platform=unknown, no initData → login falls back to wallet).
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("open_app", lang),
                        web_app=WebAppInfo(url=webapp_url),
                    )
                ]
            ]
        )
        await message.answer(t("welcome", lang), reply_markup=keyboard)

    @router.message(Command("check"))
    async def cmd_check(message: Message) -> None:
        """地址健診：/check <地址> → 多源風險判定（design 2026-08-18）。"""
        lang = _user_lang(message)
        raw = (message.text or "").strip()
        parts = raw.split(maxsplit=1)
        address = parts[1].strip() if len(parts) > 1 else ""
        if not address:
            await message.answer(t("check_usage", lang))
            return
        verdict_emoji = {
            "high_risk": "🚨",
            "caution": "⚠️",
            "no_red_flags": "✅",
        }
        verdict_key = {
            "high_risk": "check_high_risk",
            "caution": "check_caution",
            "no_red_flags": "check_no_red_flags",
        }
        try:
            data = await api.check_address(address)
        except ApiError as exc:
            if exc.code == "INVALID_ADDRESS":
                await message.answer(t("check_invalid_address", lang))
            elif exc.code == "RATE_LIMITED":
                await message.answer(t("check_rate_limited", lang))
            else:
                await message.answer(t("check_failed", lang))
            return
        except Exception:
            await message.answer(t("check_failed", lang))
            return
        v = data.get("verdict", "caution")
        lines = [
            f"{verdict_emoji.get(v, '⚠️')} {t(verdict_key.get(v, 'check_caution'), lang)}",
            f"`{address[:16]}…{address[-8:]}` ({data.get('family', '?').upper()})",
        ]
        reasons = data.get("reasons") or []
        if reasons:
            lines.append("")
            lines.extend(f"• {r}" for r in reasons[:6])
        lines.append("")
        lines.append(t("check_footer", lang))
        await message.answer("\n".join(lines))

    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(t("help", _user_lang(message)))

    @router.message(Command("link"))
    async def cmd_link(message: Message) -> None:
        lang = _user_lang(message)
        raw = message.text or ""
        token = (
            raw.strip().split(maxsplit=1)[1].strip()
            if len(raw.strip().split(maxsplit=1)) > 1
            else ""
        )
        if not token:
            await message.answer(t("link_missing_token", lang))
            return

        user = message.from_user
        try:
            result = await api.verify_link(
                token=token,
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
            )
            await message.answer(
                t("link_success", lang, username=result.get("username", "user"))
            )
        except ApiError as exc:
            await message.answer(t("link_failed", lang, detail=t(exc.code, lang)))
        except httpx.TimeoutException:
            await message.answer(t("link_timeout", lang))
        except httpx.HTTPStatusError as exc:
            code = _detail_to_code(exc)
            detail = t(code, lang) if code in MESSAGES[lang] else code
            await message.answer(t("link_failed", lang, detail=detail))
        except Exception:
            log.exception("Link error telegram_id=%s", user.id)
            await message.answer(t("unknown_error", lang))

    @router.message(Command("unlink"))
    async def cmd_unlink(message: Message) -> None:
        await message.answer(t("unlink_redirect", _user_lang(message)))

    @router.message(Command("sessions"))
    async def cmd_sessions(message: Message) -> None:
        lang = _user_lang(message)
        try:
            data = await api.list_sessions(message.from_user.id)
        except ApiError as exc:
            await message.answer(t(exc.code, lang))
            return
        except Exception:
            log.exception("List sessions error telegram_id=%s", message.from_user.id)
            await message.answer(t("sessions_failed", lang))
            return

        non_tg = [
            s
            for s in data.get("sessions", [])
            if not str(s.get("id", "")).startswith("tg:")
        ]
        if not non_tg:
            # 沒有 Web 對話可選，只回提示（仍可用 /new 重置）。
            await message.answer(t("sessions_empty", lang))
            return

        await message.answer(
            t("sessions_header", lang),
            reply_markup=_build_sessions_keyboard(data, lang),
        )

    @router.message(Command("new"))
    async def cmd_new(message: Message) -> None:
        lang = _user_lang(message)
        try:
            await api.use_session(message.from_user.id, None)
            await message.answer(t("session_new_done", lang))
        except ApiError as exc:
            await message.answer(t(exc.code, lang))
        except Exception:
            log.exception("New session error telegram_id=%s", message.from_user.id)
            await message.answer(t("unknown_error", lang))

    @router.callback_query(F.data.startswith(_SESSION_CB_PREFIX))
    async def on_session_pick(callback: CallbackQuery) -> None:
        lang = _user_lang(callback.message) if callback.message else DEFAULT_LANGUAGE
        session_id = callback.data[len(_SESSION_CB_PREFIX) :] or None
        try:
            await api.use_session(callback.from_user.id, session_id)
        except ApiError as exc:
            await callback.answer()
            if callback.message:
                await callback.message.answer(t(exc.code, lang))
            return
        except Exception:
            log.exception("Pick session error telegram_id=%s", callback.from_user.id)
            await callback.answer()
            if callback.message:
                await callback.message.answer(t("unknown_error", lang))
            return

        await callback.answer()
        if not session_id:
            text = t("session_new_done", lang)
        else:
            # 用按鈕上的標題回饋（去掉 ✅/💬 前綴）給使用者確認。
            title = session_id
            for row in (
                callback.message.reply_markup.inline_keyboard
                if callback.message and callback.message.reply_markup
                else []
            ):
                for btn in row:
                    if btn.callback_data == callback.data:
                        title = btn.text.lstrip("✅💬 ").strip()
            text = t("session_switched", lang, title=title)
        if callback.message:
            await callback.message.answer(text)

    @router.message(F.text & ~F.text.startswith("/"))
    async def handle_text(message: Message, bot: Bot) -> None:
        lang = _user_lang(message)
        user = message.from_user
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        try:
            # Send initial "analyzing" indicator
            analyzing_msg = await bot.send_message(
                chat_id=message.chat.id, text="🌀 分析中..."
            )
            result = await api.chat(
                telegram_id=user.id,
                message=message.text or "",
                language=lang,
            )
            response_text = result.get("response") or t("empty_response", lang)

            # Progressive edit: send response in ~100-char chunks with cursor
            # to simulate typing feel, editing the same message
            chunk_size = 100
            accumulated = ""
            for i in range(0, len(response_text), chunk_size):
                chunk = response_text[i : i + chunk_size]
                accumulated += chunk
                cursor = "▌" if i + chunk_size < len(response_text) else ""
                try:
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=analyzing_msg.message_id,
                        text=accumulated + cursor,
                    )
                    await asyncio.sleep(0.05)
                except Exception:
                    break

            # Final message edit: remove cursor
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=analyzing_msg.message_id,
                    text=response_text,
                )
            except Exception:
                pass

        except ApiError as exc:
            await message.answer(t(exc.code, lang))
        except httpx.TimeoutException:
            await message.answer(t("timeout", lang))
        except httpx.HTTPStatusError as exc:
            code = _detail_to_code(exc)
            msg = t(code, lang) if code in MESSAGES[lang] else t("unknown_error", lang)
            await message.answer(msg)
        except Exception:
            log.exception("Chat error telegram_id=%s", user.id)
            await message.answer(t("unknown_error", lang))

    return router


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    log.info("Starting CryptoMind Telegram Bot v%s", __version__)
    try:
        config = BotConfig.from_env()
    except ValueError as exc:
        log.error("Configuration error: %s", exc)
        sys.exit(1)

    log.info("API base URL : %s", config.api_base_url)
    log.info("Bot mode     : %s", config.mode)

    # 不使用 HTML/Markdown parse mode：訊息與 AI 回覆皆以純文字傳送，
    # 避免內容含 < > & 或 *_ 等字元時 Telegram 回 "can't parse entities"
    # 而整則訊息送不出去（例如 "/link <token>"、"BTC < 60000"、程式碼片段）。
    bot = Bot(token=config.token)
    dp = Dispatcher()
    dp.include_router(
        create_handlers(
            ApiClient(config.api_base_url, config.bot_secret), config.webapp_url
        )
    )

    async def on_startup() -> None:
        # 註冊指令選單，讓使用者在輸入框看到 / 指令清單（zh-TW + en）。
        zh_commands = [
            BotCommand(command="sessions", description="選擇 / 切換對話"),
            BotCommand(command="new", description="開新對話"),
            BotCommand(command="link", description="綁定平台帳號"),
            BotCommand(command="unlink", description="解除帳號綁定"),
            BotCommand(command="help", description="顯示指令說明"),
        ]
        en_commands = [
            BotCommand(command="sessions", description="Pick / switch conversation"),
            BotCommand(command="new", description="Start a new conversation"),
            BotCommand(command="link", description="Bind platform account"),
            BotCommand(command="unlink", description="Unbind account"),
            BotCommand(command="help", description="Show command help"),
        ]
        try:
            await bot.set_my_commands(en_commands)  # default
            await bot.set_my_commands(zh_commands, language_code="zh")
        except Exception as exc:  # noqa: BLE001
            log.warning("set_my_commands failed: %s", exc)
        # Set the chat menu button to launch the Mini App. This is the
        # persistent entry point that opens the page with a real Telegram
        # context (platform + initData); a plain URL menu button would only
        # open the in-app browser and break Telegram login.
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="CryptoMind",
                    web_app=WebAppInfo(url=config.webapp_url),
                )
            )
            log.info("Chat menu button set to Web App: %s", config.webapp_url)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_chat_menu_button failed: %s", exc)
        log.info("Bot startup complete — listening for updates")

    async def on_shutdown() -> None:
        log.info("Shutting down bot...")
        await bot.session.close()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    if config.mode == "webhook":
        await dp.start_webhook(
            listen=config.webhook_host,
            port=8443,
            path=config.webhook_path,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
        )
    else:
        await dp.start_polling(bot, on_startup=on_startup, on_shutdown=on_shutdown)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot stopped by user")
