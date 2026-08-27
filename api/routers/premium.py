"""
Premium 會員相關 API
"""

import asyncio
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.middleware.rate_limit import limiter
from api.utils import logger, run_sync
from core.config import (
    TEST_MODE,
    TON_IS_TESTNET,
    TON_PAYMENT_PRICES,
    TON_PREMIUM_USD_ANCHOR,
    TON_RECEIVING_ADDRESS,
)
from core.database.user import get_user_membership, upgrade_to_pro
from core.entitlement import entitlement_summary, resolve_entitlement_for_user
from core.orm.repositories import user_repo

# 報價有效分鐘（design §6.2：短效 TON 報價，避免波動期間金額失真）。
TON_QUOTE_EXPIRY_MINUTES = 10

router = APIRouter(prefix="/api/premium", tags=["Premium"])

PLAN_MONTHS = {
    "premium_monthly": 1,
    "premium_yearly": 12,
}


def _resolve_premium_ton_amount(plan: str) -> float:
    """計算 Premium 方案的 TON 金額（定價 v3，DANNY 核准決策 #5：純 USD 錨定）。

    策略：amount_ton = usd_anchor / ton_usd_price（不設最低 TON 顆數）。
    條款對外一致描述為「USD 12／108 約當 TON」——不論 TON 漲跌，買方付出的
    USD 等值即為錨定價。

    - TON/USD 來源：get_ton_usd_price()（CoinGecko → TonAPI，shared_cache 60s）
    - 價格來源失敗（None）→ fallback TON_PAYMENT_PRICES（靜態 env，防掛掉）
    """
    usd_anchor = TON_PREMIUM_USD_ANCHOR.get(plan)
    if not usd_anchor:
        # 未設定錨定（理論不發生，env 有預設）→ 退回靜態價
        return TON_PAYMENT_PRICES.get(plan, 0.0)

    from core.tools.crypto_modules.ton_price import get_ton_usd_price

    ton_usd = get_ton_usd_price()  # sync，呼叫端已在 run_sync 或此函式在 sync context
    if not ton_usd or ton_usd <= 0:
        # 價格來源失敗 → 靜態 fallback（不讓付款流程掛掉）
        return TON_PAYMENT_PRICES.get(plan, 0.0)

    return round(usd_anchor / ton_usd, 4)


def _normalize_legacy_membership(legacy_membership: dict) -> dict:
    return {
        "is_premium": bool(legacy_membership.get("is_premium")),
        "membership_tier": legacy_membership.get("tier") or "free",
        "days_remaining": 0,
    }


def _should_fallback_to_legacy_membership(exc: Exception) -> bool:
    if isinstance(exc, ModuleNotFoundError):
        return True

    message = str(exc)
    return "async_generator" in message and "context manager" in message


def _record_used_payment(payment_id: str, user_id: str) -> None:
    from core.database.connection import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO used_payments (payment_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (payment_id, user_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError("payment already used")
    finally:
        conn.close()


class UpgradeRequest(BaseModel):
    plan: Literal["premium_monthly", "premium_yearly"] = "premium_monthly"
    tx_hash: Optional[str] = None
    # TON Connect payment path
    order_token: Optional[str] = None  # signed order binding user+plan+amount
    comment: Optional[str] = None  # on-chain memo used to locate the transfer
    months: int = Field(default=1, ge=1, le=24)


class TonOrderRequest(BaseModel):
    plan: Literal["premium_monthly", "premium_yearly"] = "premium_monthly"


@router.post("/ton-order")
@limiter.limit("20/minute")
async def create_ton_payment_order(
    request: Request,
    body: TonOrderRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a TON payment order. Returns the receiving address, exact amount,
    and a unique on-chain comment the wallet must attach. The signed
    `order_token` binds this order to the user for verification at upgrade.
    """
    from api.ton_verification import create_ton_order

    plan = (body.plan or "premium_monthly").strip().lower()
    if plan not in PLAN_MONTHS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    # 定價 v2：USD 錨定 + 即時 TON 換算 + floor 保護（sync 內有 httpx，包 run_sync）
    amount = await run_sync(_resolve_premium_ton_amount, plan)
    if not amount or amount <= 0:
        raise HTTPException(status_code=500, detail="TON price not configured")

    order = create_ton_order(current_user["user_id"], plan, amount)
    return {"success": True, **order}


@router.get("/pricing")
async def get_pricing_plans():
    # H6 修復（2026-07-20）：get_prices 內部呼叫 sync get_cache（Redis + DB SELECT），
    # 過去直接在 async route 內呼叫會凍結 event loop。cache miss 時每個 /pricing
    # request 都會卡住。
    # 定價 v2：pricing.premium 顯示 USD 錨定價；ton.prices 顯示動態 TON 金額
    #（USD/TON 即時換算 + floor 保護；價格來源失敗 fallback 靜態價）
    ton_monthly = await run_sync(_resolve_premium_ton_amount, "premium_monthly")
    ton_yearly = await run_sync(_resolve_premium_ton_amount, "premium_yearly")
    usd_monthly = TON_PREMIUM_USD_ANCHOR.get("premium_monthly", 12.0)
    usd_yearly = TON_PREMIUM_USD_ANCHOR.get("premium_yearly", 108.0)

    return {
        "success": True,
        "pricing": {
            "premium": {
                "monthly": usd_monthly,
                "yearly": usd_yearly,  # USD 錨定（送 3 個月）
            }
        },
        "savings": {
            "premium_yearly_save": round(usd_monthly * 3, 2),
        },
        # TON Connect payment (Web DApp) — 動態 TON 金額
        "ton": {
            "network": "testnet" if TON_IS_TESTNET else "mainnet",
            "receiving_address": TON_RECEIVING_ADDRESS,
            "prices": {
                "premium_monthly": ton_monthly,
                "premium_yearly": ton_yearly,
                "create_post": TON_PAYMENT_PRICES.get("create_post"),
                "tip": TON_PAYMENT_PRICES.get("tip"),
            },
            # 報價時間（design §6.2）：TON 金額隨匯率波動，UI 需顯示時間並在
            # 過期後重取報價。amount 仍由後端 ton-order 簽入，client 不可改。
            "quote_timestamp": datetime.now(timezone.utc).isoformat(),
            "quote_expiry_minutes": TON_QUOTE_EXPIRY_MINUTES,
        },
    }


@router.post("/upgrade")
@limiter.limit("10/minute")
async def upgrade_to_premium(
    request: Request,
    body: UpgradeRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Upgrade to Premium membership.

    In production: requires a TON Connect order (order_token + comment) verified
    against an on-chain transfer via toncenter.
    In TEST_MODE: tx_hash is optional and verification is skipped.
    """
    user_id = current_user["user_id"]

    plan = (body.plan or "premium_monthly").strip().lower()
    if plan not in PLAN_MONTHS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    months = PLAN_MONTHS[plan]

    tx_hash = body.tx_hash

    if not TEST_MODE:
        if body.order_token and body.comment:
            # --- TON Connect payment path ---
            from api.ton_verification import (
                verify_ton_order_token,
                verify_ton_payment,
            )

            order = verify_ton_order_token(body.order_token, user_id)
            if order.get("c") != body.comment:
                raise HTTPException(
                    status_code=400, detail="Comment does not match order"
                )
            if order.get("p") != plan:
                raise HTTPException(status_code=400, detail="Plan does not match order")

            # Amount is taken from the signed order, not the client request.
            payment = await verify_ton_payment(body.comment, float(order["a"]))

            tx_hash = payment.get("tx_hash") or body.comment
        else:
            raise HTTPException(
                status_code=400,
                detail="order_token and comment (TON) are required",
            )
    else:
        if not tx_hash:
            import uuid

            tx_hash = f"test_{uuid.uuid4().hex[:16]}"

    try:
        current_membership = await user_repo.get_membership(user_id)

        if not current_membership:
            raise HTTPException(status_code=404, detail="User not found")

        # 先升級：upgrade_to_pro 內含 tx_hash 去重（查 membership_payments +
        # tx_hash UNIQUE 約束），且升級與記帳在同一 DB 交易內原子完成。
        # 過去的 _record_used_payment（寫另一張 used_payments 表）在升級前執行，
        # 一旦升級失敗會讓 payment「已標記 used 但會員未授予」，使用者無法重試。
        # 改為升級成功後再標記 used_payments（輔助記錄，失敗只 log）。
        try:
            success = await run_sync(
                lambda: upgrade_to_pro(
                    user_id=user_id,
                    months=months,
                    tx_hash=tx_hash,
                )
            )
        except ValueError as e:
            # tx_hash 已存在於 membership_payments → 重複提交
            msg = str(e)
            if "已被處理" in msg or "already" in msg.lower() or "hash" in msg.lower():
                raise HTTPException(status_code=409, detail="Payment has already been used")
            raise HTTPException(status_code=400, detail=msg)

        if not success:
            raise HTTPException(status_code=500, detail="Upgrade failed")

        # 升級成功後標記 used_payments（輔助索引；此時失敗無害——升級與
        # membership_payments 記帳已原子完成，replay 由 tx_hash UNIQUE 擋下）
        if not TEST_MODE and body.comment:
            try:
                await run_sync(lambda: _record_used_payment(body.comment, user_id))
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.warning(
                    "Upgrade succeeded but used_payments mark failed (non-fatal): %s — %s",
                    body.comment,
                    e,
                )

        new_membership = await user_repo.get_membership(user_id)

        logger.info(
            "User %s upgraded to Premium, plan=%s, months=%d, tx_hash=%s",
            user_id,
            plan,
            months,
            tx_hash[:16] if tx_hash else "none",
        )

        return {
            "success": True,
            "message": f"Successfully upgraded to Premium for {months} month(s)!",
            "plan": plan,
            "months": months,
            "membership": new_membership,
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error("Premium upgrade failed for user %s: %s", user_id, e)
        raise HTTPException(
            status_code=500, detail="Upgrade failed, please try again later"
        )


@router.get("/status")
async def get_premium_status(
    current_user: dict = Depends(get_current_user),
):
    try:
        user_id = current_user["user_id"]
        try:
            membership = await user_repo.get_membership(user_id)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            if not _should_fallback_to_legacy_membership(exc):
                raise
            logger.warning(
                "Async membership store unavailable, falling back to legacy DB layer: %s",
                exc,
            )
            membership = _normalize_legacy_membership(
                await run_sync(get_user_membership, user_id)
            )

        if not membership:
            raise HTTPException(status_code=404, detail="User not found")

        # Entitlement（design §9.4）：單一來源 resolve，與 cron / wallet_monitor 一致。
        ent = await run_sync(resolve_entitlement_for_user, user_id)

        return {
            "success": True,
            "membership": membership,
            "entitlement": entitlement_summary(ent),
        }

    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error("Failed to get premium status for user %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Failed to get status")
