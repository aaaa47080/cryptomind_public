"""
TON 錢包總資產查詢工具（組合視圖）

把 get_ton_balance（原生 TON）+ get_ton_jetton_balances（所有 jetton）
合成單一「錢包總覽」：一次回傳 TON 餘額、所有 jetton（含 USD/TON 估值）、
總資產 USD 估值。讓 agent 能回答「我錢包總共多少錢」「我有哪些資產」。

唯讀、低風險（同 get_ton_balance）：公開鏈上資料，不碰私鑰、不簽章。
設計：組合兩個既有工具，不重複實作網路層——單一真相來源。
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def get_my_wallet_overview(address: str = "") -> dict:
    """查詢 TON 錢包的完整資產總覽（原生 TON + 所有 jetton + 總估值）。

    查「我錢包」時可不傳 address——自動用登入身份查詢；查其他錢包才傳
    TON 地址（EQ... 或 UQ... 開頭）。

    回傳：TON 餘額、每個 jetton 的餘額與 USD/TON 估值、以及錢包總資產
    USD 估值（TON + jetton 合計）。唯讀，不碰私鑰。

    Args:
        address: TON 地址（EQ... 或 UQ... 開頭）。省略 = 查登入使用者的錢包。
    """
    from .ton_balance import get_ton_balance
    from .ton_jetton_balances import get_ton_jetton_balances

    # 兩個子工具各自處理 address 驗證與登入帶入；錯誤會回 {"error": ...}。
    ton_result = await get_ton_balance.ainvoke({"address": address})
    jetton_result = await get_ton_jetton_balances.ainvoke({"address": address})

    # 解析結果（任一失敗都降級，不全盤失敗）。
    ton_balance = 0.0
    ton_error = None
    if isinstance(ton_result, dict) and "error" not in ton_result:
        ton_balance = float(ton_result.get("balance_ton", 0) or 0)
    else:
        ton_error = ton_result.get("error") if isinstance(ton_result, dict) else "TON query failed"

    jetton_balances = []
    jetton_usd_total = 0.0
    jetton_error = None
    if isinstance(jetton_result, dict) and "error" not in jetton_result:
        jetton_balances = jetton_result.get("balances", []) or []
        for b in jetton_balances:
            jetton_usd_total += float(b.get("usd_value", 0) or 0)
    else:
        jetton_error = (
            jetton_result.get("error") if isinstance(jetton_result, dict) else "jetton query failed"
        )

    # TON 的 USD 估值：用 CoinGecko 現價（與 swap_limits 同一來源）。
    # 查不到幣價 → ton_usd_value=0 並標明（不假精確）。
    ton_usd_value = 0.0
    try:
        import httpx

        from .ton_price import get_ton_usd_price

        ton_price = get_ton_usd_price()
        if ton_price and ton_price > 0:
            ton_usd_value = ton_balance * ton_price
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except (httpx.HTTPError, OSError, ValueError, TypeError):
        # 幣價查詢失敗不影響主功能（僅 TON 估值缺，agent 可說明）。
        logger.debug("wallet overview: TON price lookup failed", exc_info=True)

    usd_total = round(jetton_usd_total + ton_usd_value, 2)
    return {
        "address": ton_result.get("address") if isinstance(ton_result, dict) else "",
        "ton_balance": ton_balance,
        "ton_usd_value": round(ton_usd_value, 2),
        "jetton_count": len(jetton_balances),
        "jettons": jetton_balances,
        "jetton_usd_total": round(jetton_usd_total, 2),
        "usd_total": usd_total,
        "partial_errors": [e for e in (ton_error, jetton_error) if e],
        "source": "toncenter+tonapi+coingecko",
    }
