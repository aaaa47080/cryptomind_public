"""
Korea Stock Market Router — 韓股市場
Data source: yfinance library (handles Yahoo Finance cookie/crumb automatically)
Symbol format: 005930.KS (KOSPI Samsung), 035420.KQ (KOSDAQ Naver)
Switched from direct HTTP calls to yfinance to avoid production server IP blocks.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from api.deps import get_optional_current_user
from api.middleware.rate_limit import limiter
from api.routers.yf_helpers import (
    fetch_klines_sync,
    fetch_news,
    fetch_quotes,
    fetch_technicals_sync,
)
from api.user_llm import resolve_user_llm_credentials
from api.utils import logger

router = APIRouter(prefix="/api/krstock", tags=["Korea Stock"])

MARKET_DATA_UNAVAILABLE_MESSAGE = "目前無法取得韓股行情，已回傳空資料供前端安全降級"

# ── Cache ──────────────────────────────────────────────────────────────────────
_cache: dict = {}


def _get_cache(key: str):
    if key in _cache:
        data, expiry = _cache[key]
        if datetime.now(timezone.utc) < expiry:
            return data
    return None


def _set_cache(key: str, data, ttl: int = 300):
    _cache[key] = (data, datetime.now(timezone.utc) + timedelta(seconds=ttl))


# ── Yahoo Finance headers (kept for search endpoint only) ─────────────────────
_YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# ── Curated Korea stock name table ─────────────────────────────────────────────
_KR_STOCK_NAMES: dict[str, dict] = {
    # Indices
    "^KS11": {"zh": "KOSPI", "en": "KOSPI"},
    "^KQ11": {"zh": "KOSDAQ", "en": "KOSDAQ"},
    # 科技 / 半導體 (KOSPI)
    "005930.KS": {"zh": "三星電子", "en": "Samsung"},
    "000660.KS": {"zh": "SK 海力士", "en": "SK Hynix"},
    "066570.KS": {"zh": "LG電子", "en": "LG Electronics"},
    "034730.KS": {"zh": "SK 控股", "en": "SK Holdings"},
    # 汽車
    "005380.KS": {"zh": "現代汽車", "en": "Hyundai Motor"},
    "000270.KS": {"zh": "起亞", "en": "Kia"},
    "012330.KS": {"zh": "現代摩比斯", "en": "Mobis"},
    # 化學 / 材料
    "051910.KS": {"zh": "LG 化學", "en": "LG Chem"},
    "096770.KS": {"zh": "SK 創新", "en": "SK Innovation"},
    "003670.KS": {"zh": "浦項鋼鐵", "en": "POSCO"},
    # 金融 / 保險
    "105560.KS": {"zh": "KB 金融", "en": "KB Financial"},
    "055550.KS": {"zh": "新韓金融", "en": "Shinhan"},
    "086790.KS": {"zh": "韓國銀行", "en": "Hana Financial"},
    # 生技 / 醫療
    "207940.KS": {"zh": "三星生物", "en": "Samsung Biologics"},
    "068270.KS": {"zh": "Celltrion", "en": "Celltrion"},
    # 消費 / 零售
    "004370.KS": {"zh": "農心", "en": "Nongshim"},
    "097950.KS": {"zh": "CJ 第一製糖", "en": "CJ CheilJedang"},
    # 電信
    "017670.KS": {"zh": "SK 電信", "en": "SK Telecom"},
    "030200.KS": {"zh": "KT", "en": "KT"},
    # KOSDAQ
    "035420.KQ": {"zh": "Naver", "en": "Naver"},
    "035720.KQ": {"zh": "Kakao", "en": "Kakao"},
    "247540.KQ": {"zh": "EcoPro BM", "en": "EcoPro BM"},
    "086520.KQ": {"zh": "EcoPro", "en": "EcoPro"},
    "196170.KQ": {"zh": "Alteogen", "en": "Alteogen"},
    # ETF
    "069500.KS": {"zh": "KODEX 200 ETF", "en": "KODEX 200 ETF"},
    "133690.KS": {"zh": "TIGER 나스닥100 ETF", "en": "TIGER 나스닥100 ETF"},
}

DEFAULT_KR_SYMBOLS = [
    "005930.KS",
    "000660.KS",
    "005380.KS",
    "035420.KQ",
    "051910.KS",
    "105560.KS",
    "017670.KS",
    "069500.KS",
]


def _normalise(symbol: str) -> str:
    s = symbol.upper()
    # Indices like ^KS11, ^KQ11 — skip .KS suffix
    if s.startswith("^"):
        return s
    # Already has exchange suffix
    if s.endswith(".KS") or s.endswith(".KQ"):
        return s
    # Numeric code: default to KOSPI (.KS)
    return s + ".KS"


# ── Quote / Technicals — 改用 yfinance（自動處理 cookie/crumb）────────────────


async def _fetch_quotes_yahoo_batch(symbols: list[str]) -> list[dict]:
    """Fetch quotes via yfinance (handles Yahoo Finance auth automatically)."""
    return await fetch_quotes(
        symbols, _KR_STOCK_NAMES, decimal_places=0, default_currency="KRW"
    )


async def _fetch_technicals_yahoo(symbol: str) -> dict:
    """Fetch RSI(14) and 52w high/low via yfinance."""
    return await asyncio.to_thread(fetch_technicals_sync, symbol, 0)


def _fetch_extras_sync(symbol: str) -> dict:
    """Fetch fundamentals via yfinance (shared implementation from yf_helpers)."""
    from api.routers.yf_helpers import fetch_extras_sync

    return fetch_extras_sync(symbol)


async def _fetch_extras(symbol: str) -> dict:
    from api.routers.yf_helpers import fetch_extras

    return await fetch_extras(symbol)


@router.get("/market")
async def get_kr_market(symbols: Optional[str] = None):
    targets = (
        [_normalise(s.strip()) for s in symbols.split(",") if s.strip()]
        if symbols
        else DEFAULT_KR_SYMBOLS
    )
    cache_key = "market:" + ",".join(targets)
    cached = _get_cache(cache_key)
    if cached:
        return cached

    quotes = await _fetch_quotes_yahoo_batch(targets)
    data = {
        "quotes": quotes,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    if len(quotes) != len(targets):
        data["partial_failure"] = True
        data["warning"] = MARKET_DATA_UNAVAILABLE_MESSAGE

    # 只 cache 有資料的結果，避免空結果被 cache 5 分鐘
    if quotes:
        _set_cache(cache_key, data)
    return data


@limiter.limit("20/minute")



@router.get("/pulse/{symbol}")
async def get_kr_pulse(
    request: Request,
    symbol: str,
    deep_analysis: bool = False,
    force_refresh: bool = False,
    lang: str = "zh-TW",
    x_user_llm_provider: Optional[str] = Header(None),
    current_user: Optional[dict] = Depends(get_optional_current_user),
):
    sym = _normalise(symbol)

    cache_key = f"pulse:{sym}"
    if not deep_analysis:
        cached = _get_cache(cache_key)
        if cached:
            return cached

    quotes, tech, news_items, extras = await asyncio.gather(
        _fetch_quotes_yahoo_batch([sym]),
        _fetch_technicals_yahoo(sym),
        fetch_news([sym], limit_per=5),
        _fetch_extras(sym),
    )
    if not quotes:
        raise HTTPException(
            status_code=404, detail=f"Korean stock symbol \"{sym}\" not found or data is currently unavailable"
        )

    q = quotes[0]
    price = q["price"]
    chg_p = q["changePercent"]
    display_name = q["name"]
    currency = q.get("currency", "KRW")

    trend_str = "走升" if chg_p > 0 else ("走跌" if chg_p < 0 else "持平")
    rsi = tech.get("rsi")
    rsi_str = ""
    if isinstance(rsi, (int, float)):
        if rsi > 70:
            rsi_str = "，RSI 顯示可能處於超買區間"
        elif rsi < 30:
            rsi_str = "，RSI 顯示可能處於超賣區間"
        else:
            rsi_str = "，RSI 落在中性區間"

    summary = (
        f"{display_name} ({sym}) 目前報價為 {price:,.0f} {currency}，"
        f"24小時{trend_str} ({chg_p:+.2f}%){rsi_str}。"
    )
    key_points = [
        f"RSI(14): {tech.get('rsi', 'N/A')}",
        f"MACD Histogram: {tech.get('macd_histogram', 'N/A')}",
        f"MA20: {int(tech['ma20']):,} {currency}"
        if isinstance(tech.get("ma20"), (int, float))
        else "MA20: N/A",
        f"MA50: {int(tech['ma50']):,} {currency}"
        if isinstance(tech.get("ma50"), (int, float))
        else "MA50: N/A",
        f"52W High: {int(tech['52w_high']):,} {currency}"
        if isinstance(tech.get("52w_high"), (int, float))
        else "52W High: N/A",
        f"52W Low: {int(tech['52w_low']):,} {currency}"
        if isinstance(tech.get("52w_low"), (int, float))
        else "52W Low: N/A",
        f"24H Change: {chg_p:+.2f}%",
    ]

    source_mode = "on_demand"
    credentials = None
    ai_error = None
    cached_at = None
    cache_expires_at = None
    cooldown_remaining = None
    if deep_analysis:
        credentials = await resolve_user_llm_credentials(
            current_user, x_user_llm_provider
        )
    if credentials:
        from api.routers.deep_analysis_helper import get_deep_analysis

        vol_str = f"{extras.get('volume', 0):,}" if extras.get("volume") else "N/A"
        avg_vol = extras.get("avg_volume")
        if avg_vol and extras.get("volume"):
            vol_ratio = extras["volume"] / avg_vol
            vol_context = f"{vol_str} (均量 {avg_vol:,}，比值 {vol_ratio:.1f}x)"
        else:
            vol_context = vol_str
        mc = extras.get("market_cap")
        if mc:
            if mc >= 1e12:
                mc_str = f"{mc / 1e12:.2f}兆 {currency}"
            elif mc >= 1e8:
                mc_str = f"{mc / 1e8:.0f}億 {currency}"
            else:
                mc_str = f"{mc:,} {currency}"
        else:
            mc_str = "N/A"
        pe_str = str(extras.get("pe_ratio", "N/A"))
        pb_str = str(extras.get("pb_ratio", "N/A"))
        beta_str = str(extras.get("beta", "N/A"))
        dy = extras.get("dividend_yield")
        dy_str = f"{dy:.2f}%" if dy is not None else "N/A"
        eps_str = str(extras.get("eps", "N/A"))
        rg = extras.get("revenue_growth")
        rg_str = f"{rg:+.1f}%" if rg is not None else "N/A"
        eg = extras.get("earnings_growth")
        eg_str = f"{eg:+.1f}%" if eg is not None else "N/A"
        pm = extras.get("profit_margins")
        pm_str = f"{pm:.1f}%" if pm is not None else "N/A"
        tp = extras.get("target_price")
        if tp and price:
            upside = (tp - price) / price * 100
            tp_str = f"{tp} ({upside:+.1f}%)"
        elif tp:
            tp_str = str(tp)
        else:
            tp_str = "N/A"
        rec_str = extras.get("recommendation", "").upper() or "N/A"
        sector_str = extras.get("sector") or "N/A"
        industry_str = extras.get("industry") or "N/A"

        news_str = ""
        if news_items:
            headlines = "\n".join(f"- {n['title']}" for n in news_items[:5])
            news_str = f"\n近期新聞（最新5條）:\n{headlines}"

        context = (
            f"MARKET_LABEL: 韓股 ({sym})\n"
            f"現價: {price:,.0f} {currency}\n"
            f"24H 漲跌幅: {chg_p:+.2f}%\n"
            f"成交量: {vol_context}\n"
            f"市值: {mc_str}　本益比(PE): {pe_str}　PB: {pb_str}\n"
            f"EPS(TTM): {eps_str}　股息殖利率: {dy_str}\n"
            f"營收成長: {rg_str}　獲利成長: {eg_str}　淨利率: {pm_str}\n"
            f"Beta(β): {beta_str}\n"
            f"分析師目標價: {tp_str}　分析師建議: {rec_str}\n"
            f"所屬產業: {sector_str} / {industry_str}\n"
            f"RSI(14): {tech.get('rsi', 'N/A')}\n"
            f"MACD Histogram: {tech.get('macd_histogram', 'N/A')}\n"
            f"MA20: {tech.get('ma20', 'N/A')} {currency}\n"
            f"MA50: {tech.get('ma50', 'N/A')} {currency}\n"
            f"52W High: {tech.get('52w_high', 'N/A')} {currency}\n"
            f"52W Low: {tech.get('52w_low', 'N/A')} {currency}"
            f"{news_str}"
        )
        ai_result = await get_deep_analysis(
            market="krstock",
            symbol=sym,
            context=context,
            llm_key=credentials["api_key"],
            llm_provider=credentials["provider"],
            llm_model=credentials.get("model"),
            force_refresh=force_refresh,
            user_id=(current_user or {}).get("user_id", "anon"),
            language=lang,
        )
        source_mode = ai_result.get("source_mode", source_mode)
        ai_error = ai_result.get("ai_error")
        cached_at = ai_result.get("cached_at")
        cache_expires_at = ai_result.get("cache_expires_at")
        cooldown_remaining = ai_result.get("cooldown_remaining")
        if source_mode == "deep_analysis" and ai_result.get("report"):
            summary = ai_result["report"].get("summary", summary)

    result = {
        "symbol": sym,
        "name": display_name,
        "current_price": price,
        "currency": currency,
        "change_24h": chg_p,
        "source_mode": source_mode,
        "ai_error": ai_error,
        "report": {
            "summary": summary,
            "key_points": key_points if source_mode != "deep_analysis" else [],
        },
        "technical_indicators": tech,
        "fundamentals": extras,
        "news": [
            {
                "title": n["title"],
                "url": n.get("url", ""),
                "published": n.get("published", ""),
            }
            for n in (news_items or [])[:5]
        ],
        "cached_at": cached_at,
        "cache_expires_at": cache_expires_at,
        "cooldown_remaining": cooldown_remaining,
    }
    if not deep_analysis:
        _set_cache(cache_key, result, ttl=300)
    return result


@limiter.limit("30/minute")



@router.get("/klines/{symbol}")
async def get_kr_klines(request: Request, symbol: str, interval: str = "1d", limit: int = 200):
    """Historical OHLCV kline data via yfinance."""
    sym = _normalise(symbol)

    cache_key = f"klines:{sym}:{interval}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    try:
        klines = await asyncio.to_thread(fetch_klines_sync, sym, interval, limit, 0)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Failed to fetch Korean stock historical data: {e}")

    result_data = {"symbol": sym, "interval": interval, "data": klines}
    _set_cache(cache_key, result_data, ttl=300)
    return result_data


@router.get("/search")
async def search_kr_stocks(q: str):
    """Search Korean stocks via Yahoo Finance search API."""
    if not q or len(q.strip()) < 1:
        return {"results": []}
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {
            "q": q,
            "lang": "en-US",
            "region": "US",
            "quotesCount": 10,
            "newsCount": 0,
            "enableFuzzyQuery": False,
            "quotesQueryId": "tss_match_phrase_query",
        }
        async with httpx.AsyncClient(timeout=8, headers=_YF_HEADERS) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        quotes = data.get("quotes", [])
        results = [
            {
                "symbol": q["symbol"],
                "name": q.get("shortname") or q.get("longname") or q["symbol"],
            }
            for q in quotes
            if (
                q.get("symbol", "").endswith(".KS")
                or q.get("symbol", "").endswith(".KQ")
            )
            and q.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND")
        ]
        return {"results": results}
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.warning(f"[krstock] search failed: {e}")
        return {"results": []}


@router.get("/news")
async def get_kr_news(symbols: Optional[str] = None, limit: int = 15):
    """Recent news for KR stocks via yfinance."""
    targets = (
        [_normalise(s.strip()) for s in symbols.split(",") if s.strip()]
        if symbols
        else DEFAULT_KR_SYMBOLS[:5]
    )
    cache_key = "news:" + ",".join(targets)
    cached = _get_cache(cache_key)
    if cached:
        return cached
    news = await fetch_news(targets, limit_per=5)
    news = news[:limit]
    data = {"data": news, "last_updated": datetime.now(timezone.utc).isoformat()}
    if news:
        _set_cache(cache_key, data, ttl=600)
    return data
