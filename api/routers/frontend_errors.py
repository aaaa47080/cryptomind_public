"""前端錯誤上報 API — error-boundary.js 的接收端。

POST /api/frontend-errors — 批量上報前端 JS 錯誤
GET  /api/frontend-errors — admin 查看前端錯誤列表
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.middleware.rate_limit import limiter
from core.audit import audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

# 記憶體環形緩衝（最近 500 筆；admin 面板讀取）
# 部署版升級為 DB 表（frontend_errors）——此處 MVP 先 in-memory
_ERROR_BUFFER: list = []
_MAX_BUFFER = 500


class FrontendError(BaseModel):
    id: str = Field(max_length=32)
    message: str = Field(max_length=500)
    stack: str = Field(default="", max_length=2000)
    context: str = Field(default="unknown", max_length=100)
    url: str = Field(default="", max_length=200)
    userAgent: str = Field(default="", max_length=200)
    timestamp: str = Field(default="", max_length=40)
    session_id: Optional[str] = Field(default=None, max_length=50)


class FrontendErrorBatch(BaseModel):
    errors: List[FrontendError] = Field(max_length=20)


@router.post("/api/frontend-errors")
@limiter.limit("10/minute")
async def report_frontend_errors(
    request: Request,
    body: FrontendErrorBatch,
    current_user: dict = Depends(get_current_user),
):
    """接收前端 JS 錯誤批量上報（error-boundary.js 每 30 秒 flush）。"""
    user_id = current_user.get("user_id", "unknown")
    for err in body.errors:
        entry = err.model_dump()
        entry["user_id"] = user_id
        entry["received_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        _ERROR_BUFFER.append(entry)
        if len(_ERROR_BUFFER) > _MAX_BUFFER:
            _ERROR_BUFFER.pop(0)

    # 高頻錯誤記 audit（取第一筆即可，避免洗版）
    if body.errors:
        audit_log(
            "frontend_error",
            user_id=user_id,
            resource_type="frontend",
            resource_id=body.errors[0].context,
            metadata={
                "error_count": len(body.errors),
                "first_message": body.errors[0].message[:100],
            },
            endpoint="/api/frontend-errors",
            success=False,
        )

    logger.warning(
        "[FrontendError] user=%s count=%d first=%s",
        user_id, len(body.errors), body.errors[0].message[:60],
    )
    return {"received": len(body.errors)}


@router.get("/api/frontend-errors")
@limiter.limit("30/minute")
async def list_frontend_errors(
    request: Request,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    """admin 查看前端錯誤（最近 N 筆）。"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return {
        "errors": _ERROR_BUFFER[-limit:],
        "total": len(_ERROR_BUFFER),
    }
