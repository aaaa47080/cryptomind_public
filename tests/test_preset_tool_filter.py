"""Preset config 與 agent 工具池整合測試（impl plan Task A2/B5）。

驗證 ``_filter_tool_metas`` 正確消費 ``context["preset_config"]``：
- 只能縮小（preset 外的工具拿不到）
- 未提供 preset_config 時完全走原路徑（向下相容）
- tool_names 為空 list 時不鎖死全部（= 未指定）
"""

from __future__ import annotations

from unittest.mock import patch

from core.agents.base_react_agent import BaseReActAgent
from core.agents.models import SubTask
from core.agents.tool_registry import ToolMetadata


class _FakeTool:
    name = "fake"
    description = "fake tool"
    args: dict = {}

    def invoke(self, kwargs):
        return kwargs


def _meta(name: str, tier: str = "free") -> ToolMetadata:
    return ToolMetadata(
        name=name,
        description=name,
        input_schema={},
        handler=_FakeTool(),
        allowed_agents=[],
        required_tier=tier,
    )


class _FakeRegistry:
    def list_for_agent(self, _agent_name):
        return [
            _meta("web_search"),
            _meta("get_crypto_price"),
            _meta("search_projects"),
            _meta("submit_trade", tier="premium"),
        ]


class _DummyAgent(BaseReActAgent):
    @property
    def name(self) -> str:
        return "cryptomind"


def _make_task(context: dict):
    return SubTask(
        step=1,
        description="test",
        agent="cryptomind",
        context=context,
    )


class TestPresetConfigFilter:
    def test_preset_config_narrows_pool(self):
        """preset_config 只保留列出的工具（縮小）。"""
        agent = _DummyAgent(
            llm_client=None, tool_registry=_FakeRegistry(), user_tier="free", user_id="u1"
        )
        with patch(
            "core.agents.base_react_agent.get_allowed_tools",
            side_effect=AssertionError("preset_config path must not hit db"),
        ):
            metas = agent._get_tool_metas(
                _make_task(
                    {
                        "preset_config": {
                            "tool_names": ["web_search", "search_projects"],
                            "action_policy": "read_only",
                            "config_hash": "abc",
                        }
                    }
                )
            )
        assert sorted(m.name for m in metas) == ["search_projects", "web_search"]

    def test_preset_config_cannot_expand_to_unknown_tools(self):
        """不在 registry 的工具名一律忽略（不可擴權）。"""
        agent = _DummyAgent(
            llm_client=None, tool_registry=_FakeRegistry(), user_tier="free", user_id="u1"
        )
        with patch(
            "core.agents.base_react_agent.get_allowed_tools",
            side_effect=AssertionError("should not hit db"),
        ):
            metas = agent._get_tool_metas(
                _make_task(
                    {
                        "preset_config": {
                            "tool_names": ["totally_unknown_tool"],
                        }
                    }
                )
            )
        assert metas == []

    def test_empty_tool_names_means_no_preset(self):
        """tool_names 空 list = 未指定 → 走原路徑（不鎖死全部）。"""
        agent = _DummyAgent(
            llm_client=None, tool_registry=_FakeRegistry(), user_tier="free", user_id="u1"
        )
        with patch(
            "core.agents.base_react_agent.get_allowed_tools",
            return_value=["web_search", "get_crypto_price"],
        ):
            metas = agent._get_tool_metas(
                _make_task({"preset_config": {"tool_names": []}})
            )
        assert sorted(m.name for m in metas) == ["get_crypto_price", "web_search"]

    def test_no_preset_config_keeps_legacy_path(self):
        """未提供 preset_config → 原本 DB 路徑不變（向下相容）。"""
        agent = _DummyAgent(
            llm_client=None, tool_registry=_FakeRegistry(), user_tier="premium", user_id="u1"
        )
        with patch(
            "core.agents.base_react_agent.get_allowed_tools",
            return_value=["web_search", "submit_trade"],
        ) as mock_db:
            metas = agent._get_tool_metas(_make_task({}))
        mock_db.assert_called_once()
        assert sorted(m.name for m in metas) == ["submit_trade", "web_search"]

    def test_premium_tool_excluded_for_free_user_via_resolver(self):
        """端到端：resolver 產生 people_projects preset_config（無 submit_trade）。"""
        from core.agents.capability_resolver import resolve_preset_config

        config = resolve_preset_config(
            {"agent_ids": ["people_projects"], "action_policy": "read_only"},
            user_tier="free",
        )
        agent = _DummyAgent(
            llm_client=None, tool_registry=_FakeRegistry(), user_tier="free", user_id="u1"
        )
        with patch(
            "core.agents.base_react_agent.get_allowed_tools",
            side_effect=AssertionError("preset path"),
        ):
            metas = agent._get_tool_metas(_make_task({"preset_config": config}))
        names = [m.name for m in metas]
        assert "submit_trade" not in names
        assert "search_projects" in names
