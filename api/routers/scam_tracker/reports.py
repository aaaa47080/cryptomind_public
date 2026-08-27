"""
可疑錢包追蹤系統 - 舉報管理 API
"""

import asyncio
import logging
import re as _re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.deps import get_current_user, get_optional_current_user
from api.middleware.rate_limit import limiter
from core.orm.config_repo import config_repo
from core.orm.repositories import user_repo
from core.orm.scam_tracker_repo import scam_tracker_repo
from core.tools.crypto_modules import goplus as _goplus
from core.tools.crypto_modules import ton_safety as _ton_safety

from .models import ScamReportCreate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Scam Tracker - Reports"])


@router.get("", response_model=dict)
async def list_scam_reports(
    scam_type: Optional[str] = Query(None, description="詐騙類型篩選"),
    status: Optional[str] = Query(
        None, description="驗證狀態篩選 (pending/verified/disputed)"
    ),
    sort_by: str = Query(
        "latest", description="排序方式 (latest/most_voted/most_viewed)"
    ),
    limit: int = Query(20, ge=1, le=100, description="每頁數量"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """
    獲取舉報列表

    公開端點，所有用戶可查看。
    """
    try:
        reports = await scam_tracker_repo.get_reports(
            scam_type=scam_type,
            status=status,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )

        return {"success": True, "reports": reports, "count": len(reports)}
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"List scam reports failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch report list, please try again later")


@router.get("/search", response_model=dict)
async def search_scam_wallet(
    wallet_address: str = Query(..., description="錢包地址"),
):
    """
    搜尋錢包是否被舉報

    公開端點，返回該錢包的舉報詳情（如果存在）。
    """
    try:
        report = await scam_tracker_repo.search_wallet(wallet_address)

        if report:
            return {"success": True, "found": True, "report": report}
        else:
            return {"success": True, "found": False, "message": "This wallet has not been reported"}
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Search scam wallet failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed, please try again later")


@router.get("/config", response_model=dict)
async def get_scam_tracker_config():
    """
    獲取詐騙追蹤系統配置

    返回詐騙類型列表和相關配置。
    """
    try:
        scam_types = await config_repo.get_config("scam_types", [])

        return {
            "success": True,
            "scam_types": scam_types,
            "verification_threshold": await config_repo.get_config(
                "scam_verification_vote_threshold", 10
            ),
            "verification_approve_rate": await config_repo.get_config(
                "scam_verification_approve_rate", 0.7
            ),
        }
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Get scam tracker config failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch config, please try again later")


# ── 地址健診 v0（design 2026-08-18）────────────────────────────────────────
# 公開、免登入：把社群舉報＋GoPlus（EVM）＋TonAPI verification（TON）合成一份
# 判定。fail-soft：單源掛不掉整體；資訊不完整判 caution 而非 no_red_flags。

_EVM_RE = _re.compile(r"^0x[0-9a-fA-F]{40}$")
_TON_FRIENDLY_RE = _re.compile(r"^[EUQ]Q[0-9A-Za-z_\-]{46}$")
_TON_RAW_RE = _re.compile(r"^0:[0-9a-fA-F]{64}$")


def _detect_family(address: str) -> Optional[str]:
    a = address.strip()
    if _EVM_RE.match(a):
        return "evm"
    if _TON_FRIENDLY_RE.match(a) or _TON_RAW_RE.match(a):
        return "ton"
    return None


@router.get("/check", response_model=dict)
@limiter.limit("30/minute")
async def address_checkup(
    request: Request,
    address: str = Query(..., min_length=8, max_length=100),
):
    """轉帳前地址健診（公開端點；風險判定＋證據摘要，不含任何用戶資料）。"""
    addr = address.strip()
    family = _detect_family(addr)
    if not family:
        raise HTTPException(
            status_code=422,
            detail="Unsupported address format (expect EVM 0x… or TON EQ/UQ…/0:…)",
        )

    reasons: list[str] = []
    caution = False
    sources: dict = {"community": {"status": "ok", "found": False}}

    # ① 社群舉報資料庫（DB；fail-soft）
    try:
        report = await scam_tracker_repo.search_wallet(addr)
        if report:
            sources["community"] = {
                "status": "ok",
                "found": True,
                "report_id": report.get("report_id") if isinstance(report, dict) else getattr(report, "report_id", None),
                "status_label": (report.get("status") if isinstance(report, dict) else getattr(report, "status", None)),
            }
            reasons.append("community_report")
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        sources["community"] = {"status": "error", "found": False}
        caution = True
        logger.info("[checkup] community source failed: %s", exc)

    # ② 家族別鏈上源（同步 httpx → to_thread；AGENTS.md 禁 sync I/O 直進 async）
    if family == "evm":
        try:
            raw = await asyncio.to_thread(_goplus.fetch_address_security_raw, addr)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raw = {"info": None, "error": str(exc)}
        flags = _goplus.goplus_malicious_flags(raw.get("info") or {})
        if raw.get("error"):
            sources["goplus"] = {"status": "error", "detail": raw["error"][:200]}
            caution = True
        else:
            sources["goplus"] = {
                "status": "ok",
                "flags": flags,
                "has_records": bool(raw.get("info")),
            }
            reasons.extend(flags)
        verdict = "high_risk" if (flags or sources["community"]["found"]) else (
            "caution" if caution else "no_red_flags"
        )
    else:
        def _ton_dict(s) -> dict:
            return {
                "verification": getattr(s, "verification", None),
                "symbol": getattr(s, "symbol", None),
                "name": getattr(s, "name", None),
                "holders_count": getattr(s, "holders_count", None),
                "has_admin": getattr(s, "has_admin", None),
                "exists": getattr(s, "exists", None),
                "signals": getattr(s, "signals", None) or {},
            }

        try:
            safety = await asyncio.to_thread(_ton_safety.assess_jetton_safety, addr)
            ton = _ton_dict(safety)
            if ton["verification"] == "blacklist":
                reasons.append("tonapi_blacklist")
            if ton["has_admin"]:
                reasons.append("jetton_admin_privilege")
                caution = True
            sources["tonapi"] = {"status": "ok", **ton}
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            sources["tonapi"] = {"status": "error", "detail": str(exc)[:200]}
            caution = True
        high = ("tonapi_blacklist" in reasons) or sources["community"]["found"]
        verdict = "high_risk" if high else ("caution" if caution else "no_red_flags")

    return {
        "success": True,
        "address": addr,
        "family": family,
        "verdict": verdict,
        "reasons": reasons,
        "sources": sources,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{report_id}", response_model=dict)
async def get_scam_report_detail(
    report_id: int, current_user: Optional[dict] = Depends(get_optional_current_user)
):
    """
    獲取舉報詳情

    公開端點，如果提供 token 則包含用戶投票狀態。
    """
    try:
        user_id = current_user.get("user_id") if current_user else None

        report = await scam_tracker_repo.get_report_by_id(
            report_id, increment_view=True, viewer_user_id=user_id
        )

        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        return {"success": True, "report": report}
    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Get scam report detail failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch report details, please try again later")


@router.post("", response_model=dict)
@limiter.limit("5/minute")
async def create_new_scam_report(
    request: Request,
    req: ScamReportCreate,
    current_user: dict = Depends(get_current_user),
):
    """
    提交新舉報

    僅 Premium 會員可使用。
    """
    try:
        user_id = current_user.get("user_id")

        # 驗證用戶是否存在
        user = await user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=401, detail="User not found or credentials have expired, please log in again"
            )

        result = await scam_tracker_repo.create_report(
            scam_wallet_address=req.scam_wallet_address,
            reporter_user_id=user_id,
            reporter_wallet_masked=req.reporter_wallet_address,
            scam_type=req.scam_type,
            description=req.description,
            transaction_hash=req.transaction_hash,
        )

        if result.get("success"):
            return {
                "success": True,
                "report_id": result["report_id"],
                "message": "Report submitted successfully",
            }
        else:
            error = result.get("error")
            detail = result.get("detail", "")

            # 處理各種錯誤情況
            if error == "premium_membership_required":
                raise HTTPException(status_code=403, detail="Premium membership required")
            elif error == "daily_limit_reached":
                limit = result.get("limit", 5)
                used = result.get("used", 0)
                raise HTTPException(
                    status_code=429, detail=f"Daily report limit reached ({used}/{limit})"
                )
            elif error == "already_reported":
                existing_id = result.get("existing_report_id")
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "This wallet has already been reported",
                        "existing_report_id": existing_id,
                    },
                )
            elif error == "invalid_scam_wallet":
                raise HTTPException(
                    status_code=400, detail=f"Invalid suspicious wallet address: {detail}"
                )
            elif error == "invalid_reporter_wallet":
                raise HTTPException(
                    status_code=400, detail=f"Invalid reporter wallet address: {detail}"
                )
            elif error == "invalid_tx_hash":
                raise HTTPException(status_code=400, detail=f"Invalid transaction hash: {detail}")
            elif error == "content_validation_failed":
                warnings = result.get("warnings", [])
                raise HTTPException(
                    status_code=400,
                    detail={"error": "Content moderation failed", "warnings": warnings},
                )
            else:
                raise HTTPException(status_code=500, detail=f"Submission failed: {error}")

    except HTTPException:
        raise
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error(f"Create scam report failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit report, please try again later")
