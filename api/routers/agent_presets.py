"""Agent Presets API（impl plan Task B4；design §13）。

治理邊界：
- 所有 endpoint 需登入（get_current_user）。
- 變更類 endpoint 為 Premium-only（design §16：自訂 Preset／Team 是 Premium 功能）。
- agent_ids／capability 鍵一律以 server 端 ProfileCatalog 驗證（不信任 client）。
- AGENT_PRESETS_ENABLED=off 時全部 404（feature flag 回滾路徑）。
- 變更成功後失效 manager cache（§13 安全要求）。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user
from api.middleware.rate_limit import limiter
from core.agents.bootstrap import invalidate_manager_cache
from core.agents.capability_resolver import resolve_preset_config
from core.agents.profile_catalog import (
    CATALOG_VERSION,
    get_profile_catalog,
)
from core.database.tools import normalize_membership_tier
from core.feature_flags import agent_presets_enabled
from core.orm.agent_presets_repo import (
    MAX_PRESETS_PER_USER,
    agent_presets_repo,
)
from core.orm.session import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent-presets"])


def _require_presets_enabled() -> None:
    if not agent_presets_enabled():
        raise HTTPException(status_code=404, detail="Agent presets are not enabled")


def _require_premium(current_user: dict) -> None:
    tier = normalize_membership_tier(current_user.get("membership_tier", "free"))
    if tier != "premium":
        raise HTTPException(
            status_code=403,
            detail="Only Premium members can manage agent presets",
        )


def _preset_to_dict(preset) -> dict:
    return {
        "preset_id": preset.preset_id,
        "name": preset.name,
        "mode": preset.mode,
        "agent_ids": list(preset.agent_ids or []),
        "analysis_mode": preset.analysis_mode,
        "action_policy": preset.action_policy,
        "capability_overrides": dict(preset.capability_overrides or {}),
        "is_default": bool(preset.is_default),
        "config_version": preset.config_version,
        "created_at": preset.created_at.isoformat() if preset.created_at else None,
        "updated_at": preset.updated_at.isoformat() if preset.updated_at else None,
    }


class AgentPresetCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=50, description="顯示名稱（1–50 字）")
    mode: Literal["single", "auto", "team"] = "single"
    agent_ids: List[str] = Field(min_length=1, max_length=4)
    analysis_mode: Literal["quick", "verified", "research"] = "quick"
    action_policy: Literal["read_only", "confirm_actions"] = "read_only"
    capability_overrides: Dict[str, bool] = Field(default_factory=dict)
    is_default: bool = False


class AgentPresetUpdateInput(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    mode: Optional[Literal["single", "auto", "team"]] = None
    agent_ids: Optional[List[str]] = Field(default=None, min_length=1, max_length=4)
    analysis_mode: Optional[Literal["quick", "verified", "research"]] = None
    action_policy: Optional[Literal["read_only", "confirm_actions"]] = None
    capability_overrides: Optional[Dict[str, bool]] = None
    is_default: Optional[bool] = None


def _validate_against_catalog(agent_ids: List[str], overrides: Dict[str, bool]) -> None:
    catalog = get_profile_catalog()
    valid, unknown = catalog.validate_agent_ids(agent_ids)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent profiles: {unknown}",
        )
    known_caps = catalog.all_capabilities()
    unknown_caps = [c for c in overrides if c not in known_caps]
    if unknown_caps:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown capabilities: {unknown_caps}",
        )
    bad_values = {c: v for c, v in overrides.items() if not isinstance(v, bool)}
    if bad_values:
        raise HTTPException(
            status_code=400,
            detail=f"Capability overrides must be boolean: {sorted(bad_values)}",
        )


@router.get("/api/agent-profiles")
@limiter.limit("30/minute")
async def list_agent_profiles(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """官方 Agent Profile catalog（唯讀）。"""
    _require_presets_enabled()
    catalog = get_profile_catalog()
    return {
        "success": True,
        "config_version": CATALOG_VERSION,
        "profiles": [p.to_api_dict() for p in catalog.list_profiles()],
    }


@router.get("/api/agent-presets")
@limiter.limit("30/minute")
async def list_agent_presets(
    request: Request,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """列出使用者 presets；Free 使用者回官方預設設定（無自訂）。"""
    _require_presets_enabled()
    user_id = current_user.get("user_id")
    presets = await agent_presets_repo.list_presets(session, user_id)
    return {
        "success": True,
        "presets": [_preset_to_dict(p) for p in presets],
        "quota": {"max": MAX_PRESETS_PER_USER, "used": len(presets)},
        "official_default": {
            "agent_ids": ["general_research"],
            "analysis_mode": "quick",
            "action_policy": "read_only",
        },
    }


@router.post("/api/agent-presets", status_code=201)
@limiter.limit("20/minute")
async def create_agent_preset(
    request: Request,
    payload: AgentPresetCreateInput,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _require_presets_enabled()
    _require_premium(current_user)
    _validate_against_catalog(payload.agent_ids, payload.capability_overrides)

    user_id = current_user.get("user_id")
    count = await agent_presets_repo.count_presets(session, user_id)
    if count >= MAX_PRESETS_PER_USER:
        raise HTTPException(status_code=409, detail="Preset limit reached")

    preset = await agent_presets_repo.create_preset(
        session,
        user_id=user_id,
        name=payload.name.strip(),
        mode=payload.mode,
        agent_ids=payload.agent_ids,
        analysis_mode=payload.analysis_mode,
        action_policy=payload.action_policy,
        capability_overrides=payload.capability_overrides,
        is_default=payload.is_default,
        config_version=CATALOG_VERSION,
    )
    invalidate_manager_cache(user_id)
    return {"success": True, "preset": _preset_to_dict(preset)}


@router.patch("/api/agent-presets/{preset_id}")
@limiter.limit("20/minute")
async def update_agent_preset(
    request: Request,
    preset_id: str,
    payload: AgentPresetUpdateInput,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _require_presets_enabled()
    _require_premium(current_user)
    user_id = current_user.get("user_id")
    preset = await agent_presets_repo.get_preset(session, user_id, preset_id)
    if preset is None:
        # 非 owner 與不存在一律 404（防枚舉）
        raise HTTPException(status_code=404, detail="Preset not found")

    next_agent_ids = payload.agent_ids or list(preset.agent_ids or [])
    next_overrides = (
        payload.capability_overrides
        if payload.capability_overrides is not None
        else dict(preset.capability_overrides or {})
    )
    _validate_against_catalog(next_agent_ids, next_overrides)

    preset = await agent_presets_repo.update_preset(
        session,
        preset,
        name=payload.name,
        mode=payload.mode,
        agent_ids=payload.agent_ids,
        analysis_mode=payload.analysis_mode,
        action_policy=payload.action_policy,
        capability_overrides=payload.capability_overrides,
    )
    if payload.is_default is True:
        await agent_presets_repo.set_default(session, user_id, preset_id)
        await session.refresh(preset)
    invalidate_manager_cache(user_id)
    return {"success": True, "preset": _preset_to_dict(preset)}


@router.delete("/api/agent-presets/{preset_id}")
@limiter.limit("20/minute")
async def delete_agent_preset(
    request: Request,
    preset_id: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _require_presets_enabled()
    _require_premium(current_user)
    user_id = current_user.get("user_id")
    deleted = await agent_presets_repo.delete_preset(session, user_id, preset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Preset not found")
    invalidate_manager_cache(user_id)
    return {"success": True}


@router.post("/api/agent-presets/{preset_id}/activate")
@limiter.limit("20/minute")
async def activate_agent_preset(
    request: Request,
    preset_id: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _require_presets_enabled()
    user_id = current_user.get("user_id")
    ok = await agent_presets_repo.set_default(session, user_id, preset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Preset not found")
    preset = await agent_presets_repo.get_preset(session, user_id, preset_id)
    invalidate_manager_cache(user_id)
    tier = normalize_membership_tier(current_user.get("membership_tier", "free"))
    summary = resolve_preset_config(
        {
            "agent_ids": list(preset.agent_ids or []),
            "mode": preset.mode,
            "analysis_mode": preset.analysis_mode,
            "action_policy": preset.action_policy,
            "capability_overrides": dict(preset.capability_overrides or {}),
        },
        user_tier=tier,
    )
    return {
        "success": True,
        "preset_id": preset_id,
        "summary": {
            "tool_count": len(summary["tool_names"]),
            "profiles": summary["profiles"],
            "action_policy": summary["action_policy"],
            "config_hash": summary["config_hash"],
        },
    }


@router.get("/api/agent-presets/{preset_id}/resolved-capabilities")
@limiter.limit("30/minute")
async def get_resolved_capabilities(
    request: Request,
    preset_id: str,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    _require_presets_enabled()
    user_id = current_user.get("user_id")
    preset = await agent_presets_repo.get_preset(session, user_id, preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    tier = normalize_membership_tier(current_user.get("membership_tier", "free"))
    resolved = resolve_preset_config(
        {
            "agent_ids": list(preset.agent_ids or []),
            "mode": preset.mode,
            "analysis_mode": preset.analysis_mode,
            "action_policy": preset.action_policy,
            "capability_overrides": dict(preset.capability_overrides or {}),
        },
        user_tier=tier,
    )
    return {"success": True, "resolved": resolved}
