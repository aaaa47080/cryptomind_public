"""Feature flags（design.md §21 回滾策略／impl plan 部署順序）。

所有新能力預設關閉；env 未設 = off。判定準則與 MCP_ENABLED 一致
（"1"/"true"/"yes"，大小寫不拘）。
"""

from __future__ import annotations

import os

_TRUTHY = ("1", "true", "yes")


def _flag(env_key: str, default: str = "") -> bool:
    return os.getenv(env_key, default).strip().lower() in _TRUTHY


def ai_studio_enabled() -> bool:
    """Phase 1：AI Studio 頁。"""
    return _flag("AI_STUDIO_ENABLED")


def agent_presets_enabled() -> bool:
    """Phase 2：preset API；off 時 preset endpoints 404、analyze 忽略 preset_id。"""
    return _flag("AGENT_PRESETS_ENABLED")


def manifund_mcp_enabled() -> bool:
    """Phase 3：Manifund MCP server（另需 MCP_ENABLED=1）。"""
    return _flag("MANIFUND_MCP_ENABLED")


def people_projects_discover_enabled() -> bool:
    """Phase 3：探索介面（Discover）。"""
    return _flag("PEOPLE_PROJECTS_DISCOVER_ENABLED")


def discover_ai_review_enabled() -> bool:
    """出資者旅程 P0-3：AI 出資者視角評估卡（design 2026-08-15）。

    子 flag 灰度用：需主 flag（Discover）＋ MCP 都開才可能 true，
    預設 off —— 上線後由 Zeabur env 控制，回滾一鍵關。
    """
    return (
        _flag("DISCOVER_AI_REVIEW_ENABLED")
        and manifund_mcp_enabled()
        and people_projects_discover_enabled()
    )


def proposal_studio_enabled() -> bool:
    """提案工作台（募資者模式，design 2026-08-16）：預設 off，Zeabur 灰度。"""
    return _flag("PROPOSAL_STUDIO_ENABLED")


def discover_oc_enabled() -> bool:
    """Discover 第二來源：Open Collective 聯邦搜尋（design 2026-08-17 §Phase 1）。

    子 flag 模式（對齊 discover_ai_review_enabled）：需 Discover 主 flag 開才可能
    true，預設 off——Zeabur env 開 DISCOVER_OC_ENABLED 灰度，回滾一鍵關。
    """
    return _flag("DISCOVER_OC_ENABLED") and people_projects_discover_enabled()
