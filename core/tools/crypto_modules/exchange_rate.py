"""Exchange Rate Service — 統一帳本的多幣種匯率。

設計：docs/plans/2026-08-21-investment-journal-design.md（DANNY Approve）

三層匯率來源：
1. 加密貨幣：CoinGecko（已有 get_crypto_price）
2. TON：ton_price.py（已有）
3. 法幣外匯：本模組新增（USD→TWD 等）

匯率凍結：record 時呼叫 get_exchange_rate()，結果存入 trade_journal
的 exchange_rate / converted_amount 欄位——歷史記錄不受之後匯率波動影響。

快取：60 秒（同一 process/Redis 內共用），避免每筆記錄都打 API。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 快取 TTL（秒）
_RATE_CACHE_TTL = 60
_rate_cache: Dict[str, Tuple[float, datetime]] = {}

# 支援的法幣對（相對 USD）
_FIAT_RATES = {
    "TWD": 31.5,  # fallback 預設
    "USD": 1.0,
    "HKD": 7.8,
    "JPY": 150.0,
    "CNY": 7.25,
    "EUR": 0.92,
}

# 支援的加密貨幣（走 CoinGecko）
_CRYPTO_SYMBOLS = {
    "BTC", "ETH", "TON", "SOL", "BNB", "XRP", "DOGE",
    "USDT", "USDC", "ADA", "AVAX", "MATIC", "DOT", "LINK",
}

# Lucide icon for each category
CATEGORY_ICONS = {
    "food": "utensils",
    "transport": "car",
    "housing": "home",
    "shopping": "shopping-bag",
    "entertainment": "film",
    "medical": "heart-pulse",
    "education": "book-open",
    "investment": "trending-up",
    "income": "banknote",
    "other": "package",
}

# 類別的 i18n key prefix
CATEGORY_I18N_PREFIX = "journal.category"


def get_exchange_rate(
    currency: str,
    base_currency: str = "TWD",
) -> Optional[float]:
    """取得 currency → base_currency 的匯率（1 unit = ? base）。

    Returns:
        匯率浮點數，或 None（無法取得）
    """
    currency = currency.strip().upper()
    base = base_currency.strip().upper()

    if currency == base:
        return 1.0

    cache_key = f"{currency}:{base}"
    cached = _rate_cache.get(cache_key)
    if cached and (datetime.now(timezone.utc) - cached[1]).total_seconds() < _RATE_CACHE_TTL:
        return cached[0]

    rate = _fetch_rate(currency, base)
    if rate and rate > 0:
        _rate_cache[cache_key] = (rate, datetime.now(timezone.utc))
    return rate


def _fetch_rate(currency: str, base: str) -> Optional[float]:
    """依幣種類型取得匯率。"""
    # 加密貨幣 → USD → base
    if currency in _CRYPTO_SYMBOLS:
        usd_rate = _get_crypto_usd(currency)
        if usd_rate and base != "USD":
            base_rate = _get_usd_to_fiat(base)
            if base_rate:
                return usd_rate * base_rate
        return usd_rate

    # 法幣 → 法幣
    if currency in _FIAT_RATES and base in _FIAT_RATES:
        from_val = _FIAT_RATES[currency]
        to_val = _FIAT_RATES[base]
        if from_val and to_val:
            return to_val / from_val

    # 嘗試即時外匯
    return _fetch_forex_rate(currency, base)


def _get_crypto_usd(symbol: str) -> Optional[float]:
    """加密貨幣 → USD（CoinGecko）。"""
    try:
        import httpx  # noqa: PLC0415

        # CoinGecko simple price API（free tier）
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": _coingecko_id(symbol), "vs_currencies": "usd"},
            timeout=5.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            for _id in data.values():
                if "usd" in _id:
                    return float(_id["usd"])
    except Exception as exc:
        logger.debug("[ExchangeRate] crypto %s failed: %s", symbol, exc)
    return None


def _get_usd_to_fiat(fiat: str) -> Optional[float]:
    """USD → 法幣。"""
    if fiat == "USD":
        return 1.0
    if fiat in _FIAT_RATES:
        return _FIAT_RATES[fiat]
    return _fetch_forex_rate("USD", fiat)


def _fetch_forex_rate(from_cur: str, to_cur: str) -> Optional[float]:
    """即時外匯匯率（fallback 靜態值 + 可選 API）。"""
    try:
        import httpx  # noqa: PLC0415

        # 對 static fallback 先嘗試（離線/免費方案）
        if from_cur in _FIAT_RATES and to_cur in _FIAT_RATES:
            return _FIAT_RATES[to_cur] / _FIAT_RATES[from_cur]

        # 可選：ExchangeRate-API free tier
        resp = httpx.get(
            f"https://api.exchangerate-api.com/v4/latest/{from_cur}",
            timeout=5.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            rates = data.get("rates", {})
            if to_cur in rates:
                return float(rates[to_cur])
    except Exception as exc:
        logger.debug("[ExchangeRate] forex %s→%s failed: %s", from_cur, to_cur, exc)
    return None


def _coingecko_id(symbol: str) -> str:
    """symbol → CoinGecko id。"""
    mapping = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "TON": "the-open-network",
        "SOL": "solana",
        "BNB": "binancecoin",
        "XRP": "ripple",
        "DOGE": "dogecoin",
        "USDT": "tether",
        "USDC": "usd-coin",
        "ADA": "cardano",
        "AVAX": "avalanche-2",
        "MATIC": "matic-network",
        "DOT": "polkadot",
        "LINK": "chainlink",
    }
    return mapping.get(symbol.upper(), symbol.lower())


def infer_category(text: str, entry_type: str = "expense") -> str:
    """從使用者輸入推斷類別。

    Args:
        text: 使用者的原始輸入（如「午餐 250」「加油 1500」）
        entry_type: trade/expense/income
    Returns:
        類別 id（expense: food/transport/.../other；
        income: salary/bonus/investment_income/other；trade: investment）
    """
    if entry_type == "trade":
        return "investment"
    if entry_type == "income":
        # UX 第二輪：收入類別關鍵詞映射（此前 hardcode "income"）
        text_lower = text.lower()
        income_rules = [
            ("salary", ["薪水", "薪資", "工资", "月薪", "salary", "payroll"]),
            ("bonus", ["獎金", "奖金", "年終", "年终", "bonus", "紅利", "红利"]),
            ("investment_income", ["股利", "配息", "利息", "投資收益", "投资收益",
                                   "dividend", "interest", "staking"]),
        ]
        for cat, keywords in income_rules:
            if any(k in text_lower for k in keywords):
                return cat
        return "other"

    text_lower = text.lower()

    # 關鍵詞 → 類別映射（按比對優先序）
    rules = [
        ("food", ["午餐", "晚餐", "早餐", "吃", "餐", "咖啡", "饮料", "喝",
                   "lunch", "dinner", "breakfast", "coffee", "food", "eat",
                   "午", "晚", "饭", "餐廳", "餐厅"]),
        ("transport", ["加油", "油錢", "停車", "捷運", "公車", "計程車", " uber",
                       "gas", "parking", "metro", "bus", "taxi", "uber", "transport",
                       "油", "车", "車"]),
        ("housing", ["房租", "水電", "電費", "瓦斯", "網路", "管理費",
                     "rent", "utility", "utilities", "internet", "mortgage",
                     "房", "住"]),
        ("shopping", ["買", "購物", "網購", "衣服", "3c", "電子",
                      "buy", "shop", "clothes", "electronics", "online"]),
        ("entertainment", ["電影", "遊戲", "旅遊", "唱歌", "看", "玩",
                          "movie", "game", "travel", "entertainment", "fun"]),
        ("medical", ["看診", "藥", "醫院", "感冒",
                     "doctor", "medicine", "hospital", "medical", "pharmacy"]),
        ("education", ["課程", "書", "學", "補習",
                       "course", "book", "study", "education", "tuition"]),
    ]

    for category, keywords in rules:
        for kw in keywords:
            if kw in text_lower:
                return category

    return "other"


def format_converted(
    amount: float,
    currency: str,
    base_currency: str = "TWD",
    exchange_rate: Optional[float] = None,
) -> str:
    """格式化換算結果（顯示用）。"""
    rate = exchange_rate or get_exchange_rate(currency, base_currency)
    if not rate:
        return f"{amount:g} {currency}"
    converted = amount * rate
    symbols = {"TWD": "NT$", "USD": "$", "HKD": "HK$", "JPY": "¥", "CNY": "¥", "EUR": "€"}
    sym = symbols.get(base_currency, base_currency)
    return f"{amount:g} {currency} (~{sym}{converted:,.0f})"
