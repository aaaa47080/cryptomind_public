"""
Tip-related API endpoints.

Tips are paid via TON Connect (on-chain transfer to the receiving wallet with a
unique comment). Verification mirrors the premium upgrade path: the wallet signs
a server-issued order, then we scan the chain for the matching transfer.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.deps import get_current_user
from api.middleware.rate_limit import limiter
from api.utils import logger, run_sync
from core.config import TEST_MODE, TON_PAYMENT_PRICES
from core.orm.forum_repo import forum_repo

from .models import CreateTipRequest, TipOrderRequest

router = APIRouter(prefix="/api/forum", tags=["Forum - Tips"])


def _record_tip_payment(payment_id: str, user_id: str) -> None:
    """Record a tip payment as used to prevent replay attacks.

    `payment_id` is the unique on-chain comment for TON tips.
    """
    from core.database.connection import get_connection

    conn = get_connection()
    cursor = None
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
        # cursor may be None if conn.cursor() raised — guard to avoid
        # NameError masking the original exception
        if cursor is not None:
            try:
                cursor.close()
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
        conn.close()


@router.post("/posts/{post_id}/tip/ton-order")
@limiter.limit("20/minute")
async def create_tip_ton_order(
    request: Request,
    post_id: int,
    body: TipOrderRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a TON payment order for tipping a post. Returns the receiving
    address, exact amount, and a unique on-chain comment the wallet must
    attach. The signed `order_token` binds this order to the user.
    """
    from api.ton_verification import create_ton_order

    post = await forum_repo.get_post_by_id(post_id, increment_view=False)
    if not post or post["is_hidden"]:
        raise HTTPException(status_code=404, detail="Post not found")
    if post["user_id"] == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot tip your own post")

    amount = (
        float(body.amount) if body.amount else float(TON_PAYMENT_PRICES.get("tip", 0.1))
    )
    order = create_ton_order(
        current_user["user_id"],
        "tip",
        amount,
        receiving_address=post["user_id"],
    )
    return {"success": True, **order}


@router.post("/posts/{post_id}/tip")
@limiter.limit("10/minute")
async def tip_post(
    request: Request,
    post_id: int,
    body: CreateTipRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        user_id = current_user["user_id"]

        post = await forum_repo.get_post_by_id(post_id, increment_view=False)
        if not post or post["is_hidden"]:
            raise HTTPException(status_code=404, detail="Post not found")
        if post["user_id"] == user_id:
            raise HTTPException(status_code=400, detail="Cannot tip your own post")

        tx_hash = body.tx_hash
        verified_amount = body.amount

        if not TEST_MODE:
            if not body.order_token or not body.comment:
                raise HTTPException(
                    status_code=400,
                    detail="order_token and comment (TON) are required for tips",
                )

            from api.ton_verification import (
                verify_ton_order_token,
                verify_ton_payment,
            )

            order = verify_ton_order_token(body.order_token, user_id)
            if order.get("p") != "tip":
                raise HTTPException(status_code=400, detail="Order is not a tip order")
            if order.get("c") != body.comment:
                raise HTTPException(
                    status_code=400, detail="Comment does not match order"
                )

            receiver = order.get("r")
            if receiver != post["user_id"]:
                raise HTTPException(
                    status_code=400, detail="Tip receiver does not match post author"
                )

            verified_amount = float(order["a"])
            payment = await verify_ton_payment(
                body.comment,
                verified_amount,
                receiving_address=receiver,
            )

            try:
                await run_sync(lambda: _record_tip_payment(body.comment, user_id))
            except ValueError:
                raise HTTPException(
                    status_code=409, detail="Payment has already been used"
                )
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                logger.error(
                    "Tip payment verified but recording failed (replay risk): %s — %s",
                    body.comment,
                    e,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Payment verified but failed to record. Please retry.",
                )

            tx_hash = payment.get("tx_hash") or body.comment
        else:
            if not tx_hash:
                import uuid

                tx_hash = f"test_tip_{uuid.uuid4().hex[:16]}"

        tip_id = await forum_repo.create_tip(
            post_id=post_id,
            from_user_id=user_id,
            to_user_id=post["user_id"],
            amount=verified_amount,
            tx_hash=tx_hash,
        )

        logger.info(
            "Tip created: post=%d, from=%s, to=%s, amount=%.2f, tx=%s",
            post_id,
            user_id,
            post["user_id"],
            verified_amount,
            tx_hash[:16] if tx_hash else "none",
        )

        return {
            "success": True,
            "message": "Tip successful",
            "tip_id": tip_id,
            "amount": verified_amount,
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        raise HTTPException(
            status_code=500, detail="Tip failed, please try again later"
        )


@router.get("/tips/sent")
async def get_sent_tips(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    try:
        user_id = current_user["user_id"]

        tips = await forum_repo.get_tips_sent(user_id, limit=limit, offset=offset)
        return {"success": True, "tips": tips, "count": len(tips)}
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get tip records")


@router.get("/tips/received")
async def get_received_tips(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    try:
        user_id = current_user["user_id"]

        tips = await forum_repo.get_tips_received(user_id, limit=limit, offset=offset)
        total = await forum_repo.get_tips_total_received(user_id)
        return {
            "success": True,
            "tips": tips,
            "count": len(tips),
            "total_received": total,
        }
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to get tip records")
