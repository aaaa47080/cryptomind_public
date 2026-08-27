"""
可疑錢包追蹤系統 - 評論 API
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.deps import get_current_user
from api.middleware.rate_limit import limiter
from core.orm.repositories import user_repo
from core.orm.scam_tracker_repo import scam_tracker_repo

from .models import CommentCreate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/comments", tags=["Scam Tracker - Comments"])


@router.get("/{report_id}", response_model=dict)
async def list_scam_comments(
    report_id: int,
    limit: int = Query(50, ge=1, le=100, description="每頁數量"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """
    獲取評論列表

    公開端點，所有用戶可查看。
    """
    try:
        comments = await scam_tracker_repo.get_comments(
            report_id=report_id, limit=limit, offset=offset
        )

        return {"success": True, "comments": comments, "count": len(comments)}
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"List scam comments failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch comment list, please try again later")


@router.post("/{report_id}", response_model=dict)
@limiter.limit("10/minute")
async def add_comment_to_report(
    report_id: int,
    request: Request,
    req: CommentCreate,
    current_user: dict = Depends(get_current_user),
):
    """
    添加評論

    僅 Premium 會員可使用，用於分享受騙經歷或補充證據。
    """
    try:
        user_id = current_user.get("user_id")

        # 驗證用戶是否存在
        user = await user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=401, detail="User not found or credentials have expired, please log in again"
            )

        result = await scam_tracker_repo.add_comment(
            report_id=report_id,
            user_id=user_id,
            content=req.content,
            transaction_hash=req.transaction_hash,
        )

        if result.get("success"):
            return {
                "success": True,
                "comment_id": result["comment_id"],
                "message": "Comment added successfully",
            }
        else:
            error = result.get("error")
            detail = result.get("detail", "")

            if error == "premium_membership_required":
                raise HTTPException(status_code=403, detail="Premium membership required")
            elif error == "report_not_found":
                raise HTTPException(status_code=404, detail="Report not found")
            elif error == "invalid_tx_hash":
                raise HTTPException(status_code=400, detail=f"Invalid transaction hash: {detail}")
            elif error == "content_validation_failed":
                warnings = result.get("warnings", [])
                raise HTTPException(
                    status_code=400,
                    detail={"error": "Content moderation failed", "warnings": warnings},
                )
            else:
                raise HTTPException(status_code=500, detail=f"Failed to add comment: {error}")

    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Add scam comment failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add comment, please try again later")
