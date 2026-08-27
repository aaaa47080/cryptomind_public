"""Capability Resolver — server-side 工具池交集的唯一權威實作。

對應 design.md §6.3 工具最終權限公式與 impl plan Task A2。

分層語意（每一層只能「縮小」，絕不擴權）：

    起點（registry 全工具）
    ∩ Agent Profile 允許（allowed_tool_categories ∪ capability 工具）
    ∩ capability_overrides 關閉項
    ∩ 會員 tier（premium-only 工具需 premium）
    ∩ 已授權工具集（get_allowed_tools / BYOK 結果，由呼叫端傳入）
    ∩ action_policy（read_only 剔除 high-risk）
    ∩ client enabled_tools（只能縮小）

fail-closed：profile 全部無效時退回 general_research；退回後仍為空則回空集合
（絕不回「全部工具」）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set

from .profile_catalog import (
    CATALOG_VERSION,
    DEFAULT_DISABLED_CAPABILITIES,
    ProfileCatalog,
    get_profile_catalog,
)

CategoryOf = Callable[[str], Optional[str]]
RiskOf = Callable[[str], str]

FALLBACK_PROFILE_ID = "general_research"


@dataclass(frozen=True)
class PresetView:
    """已通過 API 驗證的 preset 檢視（resolver 的輸入）。"""

    agent_ids: tuple
    mode: str = "single"
    analysis_mode: str = "quick"
    action_policy: str = "read_only"
    capability_overrides: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict) -> "PresetView":
        return cls(
            agent_ids=tuple(data.get("agent_ids") or ()),
            mode=str(data.get("mode", "single")),
            analysis_mode=str(data.get("analysis_mode", "quick")),
            action_policy=str(data.get("action_policy", "read_only")),
            capability_overrides=dict(data.get("capability_overrides") or {}),
        )


@dataclass(frozen=True)
class ResolvedToolPool:
    """解析結果。``tool_names`` 為空 = 本次無工具可用（fail-closed）。"""

    tool_names: frozenset
    profiles_used: tuple
    action_policy: str
    analysis_mode: str
    config_hash: str
    warnings: tuple


def _tier_allows(tool_tier: str, user_tier: str) -> bool:
    """premium-only 工具需 premium（plus 視為非 premium）。"""
    if str(tool_tier).lower() == "premium":
        return str(user_tier).lower() == "premium"
    return True


def compute_config_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def resolve_tool_pool(
    *,
    tool_metas: Sequence,
    preset: PresetView,
    user_tier: str,
    category_of: CategoryOf,
    risk_of: Optional[RiskOf] = None,
    tier_of: Optional[Callable[[str], str]] = None,
    authorized_tool_ids: Optional[Iterable[str]] = None,
    client_enabled_tools: Optional[Iterable[str]] = None,
    catalog: Optional[ProfileCatalog] = None,
) -> ResolvedToolPool:
    """解析本次實際工具池。

    Parameters
    ----------
    tool_metas:
        ToolMetadata 序列（至少有 ``name``；最好含 ``required_tier``／``risk_level``）。
    category_of:
        工具名 → tools_catalog category（查無回 None；MCP 工具通常 None）。
    risk_of / tier_of:
        工具名 → risk_level / required_tier 的查詢函式（缺省用 meta 屬性）。
    authorized_tool_ids:
        DB 端已授權集合（get_allowed_tools 結果）；None = 不套用此層。
    client_enabled_tools:
        client 傳來的 enabled_tools；只能縮小。
    """
    warnings: List[str] = []
    cat = catalog or get_profile_catalog()

    valid_ids, unknown_ids = cat.validate_agent_ids(list(preset.agent_ids))
    if unknown_ids:
        warnings.append(f"unknown agent profiles dropped: {unknown_ids}")
    if not valid_ids:
        warnings.append(
            "no valid agent profiles; fail-closed fallback to general_research"
        )
        valid_ids = [FALLBACK_PROFILE_ID]

    profiles = [p for pid in valid_ids if (p := cat.get(pid)) is not None]
    if not profiles:
        profiles = [cat.require(FALLBACK_PROFILE_ID)]

    allowed_categories: Set[str] = set()
    profile_capabilities: Set[str] = set()
    for profile in profiles:
        allowed_categories.update(profile.allowed_tool_categories)
        profile_capabilities.update(profile.capabilities)

    capability_tools: Set[str] = cat.tools_for_capabilities(profile_capabilities)

    def _meta_tier(meta) -> str:
        if tier_of is not None:
            return tier_of(meta.name)
        return str(getattr(meta, "required_tier", "free"))

    def _meta_risk(meta) -> str:
        if risk_of is not None:
            return risk_of(meta.name)
        return str(getattr(meta, "risk_level", "low"))

    # 1) Agent Profile 允許：native 工具看 category；MCP 工具看 capability 對應名稱。
    pool: Set[str] = set()
    for meta in tool_metas:
        name = meta.name
        category = category_of(name)
        if category is not None and category in allowed_categories:
            pool.add(name)
        elif name in capability_tools:
            pool.add(name)

    # 2) 預設關閉 capability（如 advanced_funds）。
    for cap in DEFAULT_DISABLED_CAPABILITIES:
        if cap in profile_capabilities:
            pool -= set(cat.tools_for_capabilities([cap]))

    # 3) capability_overrides：只能關閉（關閉 = 移除工具）；開啟不得擴權。
    for cap, enabled in (preset.capability_overrides or {}).items():
        if not isinstance(cap, str) or not isinstance(enabled, bool):
            warnings.append(f"invalid capability override ignored: {cap!r}")
            continue
        if cap not in cat.all_capabilities():
            warnings.append(f"unknown capability override ignored: {cap}")
            continue
        if not enabled:
            pool -= set(cat.tools_for_capabilities([cap]))
        elif cap not in profile_capabilities:
            warnings.append(
                f"capability '{cap}' not in selected profiles; enabling ignored"
            )

    # 4) tier 過濾（meta.required_tier）。
    meta_by_name = {meta.name: meta for meta in tool_metas}
    for name in list(pool):
        meta = meta_by_name.get(name)
        if meta is not None and not _tier_allows(_meta_tier(meta), user_tier):
            pool.discard(name)

    # 5) 已授權集合（DB/BYOK）。
    if authorized_tool_ids is not None:
        pool &= set(authorized_tool_ids)

    # 6) action_policy：read_only 剔除 high-risk。
    if preset.action_policy == "read_only":
        for name in list(pool):
            meta = meta_by_name.get(name)
            if meta is not None and _meta_risk(meta) == "high":
                pool.discard(name)

    # 7) client enabled_tools：只能縮小；空 list / None = 使用者沒指定，不過濾
    #    （語意與 _filter_tool_metas 的 user_enabled 一致，避免誤鎖全部工具）。
    if client_enabled_tools:
        requested = {t for t in client_enabled_tools if isinstance(t, str)}
        pool &= requested

    # 8) fail-closed 檢查：全空 → 退回 general_research 的安全集合再跑一次約束。
    if not pool and valid_ids != [FALLBACK_PROFILE_ID]:
        warnings.append("resolved pool empty; fail-closed retry with general_research")
        retry = PresetView(
            agent_ids=(FALLBACK_PROFILE_ID,),
            mode="single",
            analysis_mode=preset.analysis_mode,
            action_policy=preset.action_policy,
            capability_overrides={},
        )
        retry_args = dict(
            tool_metas=tool_metas,
            preset=retry,
            user_tier=user_tier,
            category_of=category_of,
            risk_of=risk_of,
            tier_of=tier_of,
            authorized_tool_ids=authorized_tool_ids,
            client_enabled_tools=client_enabled_tools,
            catalog=cat,
        )
        resolved = resolve_tool_pool(**retry_args)
        return ResolvedToolPool(
            tool_names=resolved.tool_names,
            profiles_used=resolved.profiles_used,
            action_policy=preset.action_policy,
            analysis_mode=preset.analysis_mode,
            config_hash=resolved.config_hash,
            warnings=tuple(warnings) + resolved.warnings,
        )

    config_hash = compute_config_hash(
        {
            "catalog_version": CATALOG_VERSION,
            "profiles": list(valid_ids),
            "action_policy": preset.action_policy,
            "analysis_mode": preset.analysis_mode,
            "capability_overrides": preset.capability_overrides,
            "tools": sorted(pool),
        }
    )
    return ResolvedToolPool(
        tool_names=frozenset(pool),
        profiles_used=tuple(valid_ids),
        action_policy=preset.action_policy,
        analysis_mode=preset.analysis_mode,
        config_hash=config_hash,
        warnings=tuple(warnings),
    )


def build_category_lookup() -> Dict[str, str]:
    """tool_id → category（來自 _TOOLS_SEED；供 API 層不需要 registry 時使用）。"""
    from core.database.tools import _TOOLS_SEED

    lookup: Dict[str, str] = {}
    for entry in _TOOLS_SEED:
        tool_id = entry.get("tool_id")
        category = entry.get("category")
        if tool_id and category:
            lookup[str(tool_id)] = str(category)
    return lookup


def resolve_preset_config(
    preset_data: dict,
    user_tier: str,
    client_enabled_tools: Optional[Iterable[str]] = None,
    catalog: Optional[ProfileCatalog] = None,
) -> dict:
    """API / worker 共用的便利入口：回傳可直接放入 graph_input 的 preset_config dict。"""
    preset = PresetView.from_api(preset_data)
    category_lookup = build_category_lookup()
    from core.agents.tool_registry import ToolMetadata  # 延遲 import 避免循環

    def _seed_meta(name: str, required_tier: str = "free") -> "ToolMetadata":
        return ToolMetadata(
            name=name,
            description="",
            input_schema={},
            handler=lambda **_kwargs: None,
            required_tier=required_tier,
            risk_level="low",
        )

    seed_metas = [_seed_meta(name) for name in sorted(category_lookup)]
    # MCP 工具：category 查無（None）→ 靠 capability 名稱比對
    cat = catalog or get_profile_catalog()
    mcp_names = set()
    for profile_id in preset.agent_ids:
        profile = cat.get(str(profile_id))
        if profile is not None:
            mcp_names.update(cat.tools_for_capabilities(profile.capabilities))
    seed_metas.extend(_seed_meta(n) for n in sorted(mcp_names))

    resolved = resolve_tool_pool(
        tool_metas=seed_metas,
        preset=preset,
        user_tier=user_tier,
        category_of=lambda name: category_lookup.get(name),
        client_enabled_tools=client_enabled_tools,
        catalog=cat,
    )
    return {
        "tool_names": sorted(resolved.tool_names),
        "profiles": list(resolved.profiles_used),
        "action_policy": resolved.action_policy,
        "analysis_mode": resolved.analysis_mode,
        "config_hash": resolved.config_hash,
        "warnings": list(resolved.warnings),
        "catalog_version": CATALOG_VERSION,
    }
