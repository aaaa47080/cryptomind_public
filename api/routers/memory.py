"""Memory Management API Router — 讓使用者查看/修改/刪除自己的記憶。

Endpoints:
  GET    /api/memory/facts        — 列出使用者所有記憶（分類）
  PATCH  /api/memory/facts/{key}  — 修改單一記憶內容
  DELETE /api/memory/facts/{key}  — 刪除單一記憶

記憶來源：
  - agent 主動記住（remember 工具）
  - 系統自動抽取（MemoryStore.extract_facts_from_turn）
使用者可以自行管理——查看 agent 記了什麼、修改不正確的、刪除不想要的。
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


class UpdateFactRequest(BaseModel):
    """修改記憶內容的 request body。"""

    value: str = Field(..., description="新的記憶內容", max_length=512)
    category: str = Field(
        default="fact",
        description="記憶分類（preference/holding/fact/context）",
    )


class CreateFactRequest(BaseModel):
    """新增記憶的 request body。"""

    key: str = Field(..., description="記憶標籤（英文 snake_case）", max_length=100)
    value: str = Field(..., description="記憶內容", max_length=512)
    category: str = Field(
        default="fact",
        description="記憶分類（preference/holding/fact/context）",
    )


def _get_store(user_id: str):
    """取得該使用者的 MemoryStore。"""
    from core.database.memory import MemoryStore

    return MemoryStore(user_id=user_id)


@router.get("/api/memory/facts")
@limiter.limit("30/minute")
async def list_facts(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """列出使用者所有記憶（按 category 分組，preference/holding 優先）。"""
    user_id = current_user["user_id"]
    try:
        store = _get_store(user_id)
        facts = store.read_facts()
        # 按 category 分組（read_facts 已按 preference > holding > context > fact 排序）
        result = []
        for key, info in facts.items():
            result.append({
                "key": key,
                "value": info.get("value", ""),
                "category": info.get("category", "fact"),
                "confidence": info.get("confidence", "high"),
                # c031 治理欄位（Part B UI：status 徽章＋valid_until＋verified）
                "valid_until": info.get("valid_until"),
                "status": info.get("status") or "active",
                "verified_at": info.get("verified_at"),
            })
        return {"facts": result, "total": len(result)}
    except Exception as exc:
        logger.warning(f"[memory] list_facts failed for {user_id}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to load memory") from exc


@router.post("/api/memory/facts")
@limiter.limit("20/minute")
async def create_fact(
    request: Request,
    body: CreateFactRequest,
    current_user: dict = Depends(get_current_user),
):
    """使用者手動新增一則記憶。"""
    user_id = current_user["user_id"]
    try:
        store = _get_store(user_id)
        store.write_facts([{
            "key": body.key.strip(),
            "value": body.value.strip(),
            "confidence": "high",
            "source_turn": 0,
            "category": body.category,
        }])
        return {"ok": True, "key": body.key.strip()}
    except Exception as exc:
        logger.warning(f"[memory] create_fact failed for {user_id}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to create") from exc


@router.patch("/api/memory/facts/{key}")
@limiter.limit("20/minute")
async def update_fact(
    request: Request,
    key: str,
    body: UpdateFactRequest,
    current_user: dict = Depends(get_current_user),
):
    """修改單一記憶內容。"""
    user_id = current_user["user_id"]
    # 正規化 category
    category = body.category.strip().lower() if body.category else "fact"
    if category not in ("preference", "holding", "context", "fact"):
        category = "fact"
    try:
        store = _get_store(user_id)
        store.write_facts([{
            "key": key,
            "value": body.value.strip(),
            "confidence": "high",
            "source_turn": None,
            "category": category,
        }])
        return {"key": key, "value": body.value.strip(), "category": category}
    except Exception as exc:
        logger.warning(f"[memory] update_fact failed for {user_id}/{key}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to update memory") from exc


@router.delete("/api/memory/facts/{key}")
@limiter.limit("20/minute")
async def delete_fact(
    request: Request,
    key: str,
    current_user: dict = Depends(get_current_user),
):
    """刪除單一記憶。"""
    user_id = current_user["user_id"]
    try:
        store = _get_store(user_id)
        ok = store.delete_fact(key)
        if not ok:
            raise HTTPException(status_code=500, detail="Delete failed")
        return {"key": key, "deleted": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"[memory] delete_fact failed for {user_id}/{key}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to delete memory") from exc


# ============================================================================
# c031 記憶治理：verify / history（docs/plans/2026-08-21-memory-governance-design.md）
# ============================================================================


@router.put("/api/memory/facts/{key}/verify")
@limiter.limit("20/minute")
async def verify_fact(
    request: Request,
    key: str,
    current_user: dict = Depends(get_current_user),
):
    """標記事實為「使用者已確認」（verified_at=NOW）。

    已確認的事實在 read_facts 排序中優先於 AI 推測。
    """
    user_id = current_user["user_id"]
    try:
        from api.utils import run_sync
        from core.database.base import DatabaseBase, DatabaseError

        # run_sync：同步 DB 寫入不得阻塞 event loop（2026-08-24 review；
        # rowcount=0（key 不存在/他人）不得回假成功——同 journal 修復）
        rows = await run_sync(
            DatabaseBase.execute,
            "UPDATE user_facts SET verified_at = NOW() "
            "WHERE user_id = %s AND key = %s AND status = 'active'",
            (user_id, key),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Fact not found")
        return {"key": key, "verified": True}
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except DatabaseError as exc:
        logger.warning(f"[memory] verify_fact failed for {user_id}/{key}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to verify") from exc
    except Exception as exc:
        logger.warning(f"[memory] verify_fact failed for {user_id}/{key}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to verify") from exc


@router.get("/api/memory/facts/{key}/history")
@limiter.limit("20/minute")
async def fact_history(
    request: Request,
    key: str,
    current_user: dict = Depends(get_current_user),
):
    """列出某 key 的完整事實鏈（含 superseded/expired）——審計用。"""
    user_id = current_user["user_id"]
    try:
        from api.utils import run_sync
        from core.database.base import DatabaseBase, DatabaseError

        rows = await run_sync(
            DatabaseBase.query_all,
            """SELECT id, value, confidence, category, status, supersedes_id,
                      source_turn, source_query, valid_from, valid_until,
                      verified_at, created_at, updated_at
               FROM user_facts
               WHERE user_id = %s AND key = %s
               ORDER BY created_at DESC
               LIMIT 50""",
            (user_id, key),
        )
        return {"key": key, "history": rows or []}
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except DatabaseError as exc:
        logger.warning(f"[memory] fact_history failed for {user_id}/{key}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to get history") from exc
    except Exception as exc:
        logger.warning(f"[memory] fact_history failed for {user_id}/{key}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to get history") from exc
