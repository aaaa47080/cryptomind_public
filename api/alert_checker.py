"""
Price Alert Background Checker

Polls current prices every 60 seconds and fires notifications when
alert conditions are met. Integrates with existing notification system.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds


def is_condition_met(
    condition: str,
    target: float,
    current_price: float,
    open_price: float,
) -> bool:
    """Evaluate whether an alert condition is triggered."""
    if condition == "above":
        return current_price >= target
    if condition == "below":
        return current_price <= target
    if open_price == 0:
        return False
    pct_change = (current_price - open_price) / open_price * 100
    if condition == "change_pct_up":
        return pct_change >= target
    if condition == "change_pct_down":
        return (-pct_change) >= target
    return False


def build_alert_body(alert: dict, current_price: float) -> str:
    """Build human-readable notification body for a triggered alert."""
    symbol = alert["symbol"]
    condition = alert["condition"]
    target = alert["target"]

    condition_labels = {
        "above": f"已突破目標價 {target:,.2f}",
        "below": f"已跌破目標價 {target:,.2f}",
        "change_pct_up": f"漲幅已達 {target:.1f}%",
        "change_pct_down": f"跌幅已達 {target:.1f}%",
    }
    label = condition_labels.get(condition, "條件已觸發")
    return f"{symbol} {label}，當前價格：{current_price:,.2f}"


async def _fetch_price(symbol: str, market: str) -> Optional[tuple]:
    """
    Fetch (current_price, open_price) for a symbol.
    Returns None on failure.

    Note: For crypto we bypass the langchain @tool wrapper
    (core.agents.tools.get_crypto_price) because it returns
    {"price_info": "<formatted string>"} which has no numeric price field.
    Using OKXAPIConnector.get_ticker directly gives last + open24h.
    """
    from api.utils import run_sync

    try:
        if market == "crypto":
            def _get_crypto_price_robust(sym: str):
                """從 OKX 拿 last + open24h,失敗回 None。
                symbol 可能是 BTC / BTC-USDT / BTCUSDT 各種格式,統一轉成 OKX instId。
                """
                from utils.okx_api_connector import OKXAPIConnector

                # 正規化成 OKX instId 格式 (BTC-USDT)
                s = sym.upper().replace("/", "").replace("-", "")
                if s.endswith("USDT"):
                    s = s[:-4]
                elif s.endswith("USD") and s != "USDC":
                    s = s[:-3]
                inst_id = f"{s}-USDT"

                okx = OKXAPIConnector()
                resp = okx.get_ticker(inst_id)
                if not resp or resp.get("code") != "0":
                    return None
                data = (resp.get("data") or [{}])[0]
                last = data.get("last")
                open_24h = data.get("open24h")
                if last is None:
                    return None
                return (float(last), float(open_24h) if open_24h else float(last))

            return await run_sync(_get_crypto_price_robust, symbol)

        if market == "tw_stock":
            from core.tools.tw_stock_tools import tw_stock_price

            result = await run_sync(tw_stock_price, symbol)
            price = result.get("close") or result.get("price")
            open_p = result.get("open", price)
            return (float(price), float(open_p)) if price else None

        if market == "us_stock":
            from core.tools.us_stock_tools import us_stock_price

            result = await run_sync(us_stock_price, symbol)
            price = result.get("regularMarketPrice") or result.get("price")
            open_p = result.get("regularMarketOpen") or result.get("open", price)
            return (float(price), float(open_p)) if price else None

    except Exception as e:
        logger.debug(f"Price fetch failed for {symbol} ({market}): {e}")
    return None


async def _check_single_alert(alert: dict) -> bool:
    """Check one alert and fire notification if triggered. Returns True if fired.

    Isolated as a coroutine so the outer loop can `asyncio.gather` with a
    semaphore — the old serial loop with N alerts × ~200ms per price fetch
    could exceed POLL_INTERVAL=60s once N > ~50, causing alerts to be
    checked too infrequently or pile up.
    """
    from api.routers.notifications import push_notification_to_user
    from api.utils import run_sync
    from core.database import mark_alert_triggered

    prices = await _fetch_price(alert["symbol"], alert["market"])
    if prices is None:
        return False

    current_price, open_price = prices
    triggered = is_condition_met(
        alert["condition"], alert["target"], current_price, open_price
    )
    if not triggered:
        return False

    body = build_alert_body(alert, current_price)
    # 用 default-arg bind `alert` 避免 late-binding 陷阱(若上層用 gather 並行,
    # lambda 捕獲的 alert 會是最後一個迭代值)
    try:
        notification = await run_sync(
            _create_notification_sync, alert, body, current_price
        )
        if notification:
            await push_notification_to_user(alert["user_id"], notification)
        logger.info(
            f"Alert triggered: {alert['symbol']} ({alert['condition']} {alert['target']})"
        )
    except Exception as e:
        logger.error(f"Failed to send alert notification: {e}")
        return False

    repeat = bool(alert.get("repeat"))
    await run_sync(mark_alert_triggered, alert["id"], repeat)
    return True


def _create_notification_sync(alert: dict, body: str, current_price: float):
    """Sync helper: create notification in DB. Bound parameters avoid lambda capture bugs."""
    from core.database.notifications import create_notification

    return create_notification(
        user_id=alert["user_id"],
        notification_type="price_alert",
        title=f"🔔 {alert['symbol']} 價格警報",
        body=body,
        data={
            "symbol": alert["symbol"],
            "market": alert["market"],
            "current_price": current_price,
            "alert_id": alert["id"],
        },
    )


# 並行上限:OKX API 有 rate limit,且 _db_executor 預設只有 10 thread
_ALERT_CONCURRENCY = 5


async def _check_all_alerts():
    """Run one check cycle across all active alerts (parallel with semaphore)."""
    from api.utils import run_sync
    from core.database import get_active_alerts

    alerts = await run_sync(get_active_alerts)

    if not alerts:
        return

    logger.debug(f"Checking {len(alerts)} active alerts")

    sem = asyncio.Semaphore(_ALERT_CONCURRENCY)

    async def _bounded(alert):
        async with sem:
            return await _check_single_alert(alert)

    fired = await asyncio.gather(*(_bounded(a) for a in alerts), return_exceptions=True)
    fired_count = sum(1 for r in fired if r is True)
    if fired_count:
        logger.info(f"Alert cycle: {fired_count}/{len(alerts)} triggered")


async def price_alert_check_task():
    """
    Background task: check all active alerts every POLL_INTERVAL seconds.
    Launched from api_server.py lifespan.
    """
    await asyncio.sleep(30)  # delay startup to let DB initialize
    logger.info("Price alert checker started")

    while True:
        try:
            await _check_all_alerts()
        except Exception as e:
            logger.error(f"Alert checker error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
