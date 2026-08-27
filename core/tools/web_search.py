"""
Web Search Tool — BYOK Tavily（優先）+ DuckDuckGo（免費 fallback）

金鑰策略：
- 使用者若在「工具金鑰」設定了自己的 Tavily key → 用 Tavily（品質較好）
- 否則 → 用免費 DuckDuckGo（ddgs，免 key）

注意：本模組使用 `ddgs`（原 `duckduckgo_search` 已重新命名）。
若環境裝的是舊套件，請：
    pip install ddgs && pip uninstall -y duckduckgo_search
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import httpx
from ddgs import DDGS
from langchain_core.tools import tool

from api.utils import logger

TAIPEI_TZ = timezone(timedelta(hours=8))

# Tavily 官方 REST endpoint（用 httpx 直接呼叫，避免新增套件依賴）
_TAVILY_ENDPOINT = "https://api.tavily.com/search"

# Serper.dev（Google Search wrapper）— 中文品質最優（本質是 Google）
_SERPER_ENDPOINT = "https://google.serper.dev/search"


def search_serper(query: str, api_key: str, max_results: int = 5) -> List[Dict]:
    """使用 Serper.dev（Google Search wrapper）API（需使用者自帶金鑰）。

    Serper 是 Google Search 的 API wrapper，中文搜尋品質最優（本質是 Google）。
    免費額度 2500 次/月，註冊免信用卡。BYOK：使用者自帶 key。
    """
    logger.info(f"🔎 Serper (Google) web search for: {query}")
    try:
        resp = httpx.post(
            _SERPER_ENDPOINT,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={
                "q": query,
                "gl": "tw",  # 地區：台灣（泛用，不限制結果來源）
                "hl": "zh-TW",  # 語言偏好：繁中（Serper 會據此排序）
                "num": max_results,
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("organic", []):
            results.append(
                {
                    "title": r.get("title", ""),
                    "link": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                    "published_date": r.get("date", ""),
                }
            )
        logger.info(f"✅ Serper found {len(results)} results for: {query}")
        return results
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"❌ Serper search failed ({e}); trying next engine")
        return []


def search_tavily(query: str, api_key: str, max_results: int = 5) -> List[Dict]:
    """使用 Tavily Search API（需使用者自帶金鑰）。"""
    logger.info(f"🔎 Tavily web search for: {query}")
    try:
        resp = httpx.post(
            _TAVILY_ENDPOINT,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("results", []):
            results.append(
                {
                    "title": r.get("title", ""),
                    "link": r.get("url", ""),
                    "snippet": r.get("content", ""),
                    # 文章發布日期（Tavily 對新聞類結果會回）— 模型靠它判斷資訊新舊
                    "published_date": r.get("published_date", ""),
                }
            )
        logger.info(f"✅ Tavily found {len(results)} results for: {query}")
        return results
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"❌ Tavily search failed ({e}); falling back to DuckDuckGo")
        return []


# Financial Modeling Prep — 專業金融 API，支援中文公司名 fuzzy match
_FMP_ENDPOINT = "https://financialmodelingprep.com/api/v3/search"


def search_fmp(query: str, api_key: str, max_results: int = 5) -> List[Dict]:
    """使用 Financial Modeling Prep search API（BYOK）。

    FMP 是專業金融資料 API，支援任何語言的公司名 fuzzy match。
    免費 250 次/天。比通用搜尋引擎更精準（直接回 ticker + exchange）。
    """
    logger.info(f"🔎 FMP financial search for: {query}")
    try:
        resp = httpx.get(
            _FMP_ENDPOINT,
            params={"query": query, "apikey": api_key, "limit": max_results},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data:
            results.append(
                {
                    "title": r.get("name", ""),
                    "link": r.get("exchange", ""),
                    "snippet": f"{r.get('name', '')} ({r.get('symbol', '')}) — {r.get('exchangeShortName', '')}",
                    "published_date": "",
                }
            )
        logger.info(f"✅ FMP found {len(results)} results for: {query}")
        return results
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"❌ FMP search failed ({e}); trying next engine")
        return []


def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict]:
    """
    Perform a web search using DuckDuckGo.

    Args:
        query: The search query.
        max_results: Maximum number of results to return.

    Returns:
        List of dictionaries containing 'title', 'href', and 'body'.
    """
    logger.info(f"🔎 performing web search for: {query}")
    try:
        results = []
        with DDGS() as ddgs:
            # DDGS.text() returns a generator of results
            # keywords: headers=None, region='wt-wt', safesearch='moderate', timelimit=None, backend='api'
            ddgs_gen = ddgs.text(query, max_results=max_results)
            for r in ddgs_gen:
                results.append(
                    {
                        "title": r.get("title", ""),
                        "link": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                )

        logger.info(f"✅ Found {len(results)} results for: {query}")
        return results
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"❌ Web search failed: {e}")
        return []


def search_web(query: str, max_results: int = 5) -> List[Dict]:
    """統一網路搜尋：多引擎 fallback chain。

    優先順序（BYOK，誰有 key 用誰，失敗/超額往下退）：
    1. Tavily（AI 專用，品質優，免費 1000/月）
    2. Serper（Google wrapper，中文最優，免費 2500/月）
    3. FMP（專業金融 API，中文公司名 fuzzy match，免費 250/天）
    4. DuckDuckGo（永遠 fallback，免費無限但品質差）

    多引擎串聯讓使用者疊加免費額度，並在額度用完時自動 fallback。
    """
    from core.tools.key_resolver import resolve_tool_key

    # 1. Tavily（強制 BYOK，不提供官方 fallback env）
    tavily_key = resolve_tool_key("tavily", official_env=None)
    if tavily_key:
        results = search_tavily(query, tavily_key, max_results=max_results)
        if results:
            return results

    # 2. Serper（Google wrapper，中文品質最優）
    serper_key = resolve_tool_key("serper", official_env=None)
    if serper_key:
        results = search_serper(query, serper_key, max_results=max_results)
        if results:
            return results

    # 3. FMP（專業金融 API，中文公司名 fuzzy match）
    fmp_key = resolve_tool_key("fmp", official_env=None)
    if fmp_key:
        results = search_fmp(query, fmp_key, max_results=max_results)
        if results:
            return results

    # 4. DuckDuckGo（永遠 fallback，免費無限）
    return search_duckduckgo(query, max_results=max_results)


@tool
def web_search_tool(query: str, purpose: str = "general") -> str:
    """
    Perform a general web search to find information not available in the internal database.
    Use this for:
    1. Looking up current events, news, or market sentiment.
    2. Finding specific facts (e.g., "Pi Network current price", "competitors of Solana").
    3. Verifying information.

    Args:
        query: The search query string (e.g. "Bitcoin latest news", "Pi Network mainnet launch date").
        purpose: Brief explanation of why this search is being performed (for logging).
    """
    results = search_web(query, max_results=5)

    if not results:
        return f"No results found for query: {query}"

    # 標明搜尋時間，模型才能把結果的發布日期跟「現在」比對，避免舊文當新聞
    searched_at = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")
    output = f"### Search Results for '{query}' (searched at {searched_at} UTC+8)\n\n"
    for i, res in enumerate(results, 1):
        output += f"{i}. **{res['title']}**\n"
        output += f"   {res['snippet']}\n"
        if res.get("published_date"):
            output += f"   Published: {res['published_date']}\n"
        output += f"   Source: {res['link']}\n\n"
    output += (
        "Note: results without a published date may be outdated — "
        "verify time-sensitive claims against real-time tools."
    )

    return output
