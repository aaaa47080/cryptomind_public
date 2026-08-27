"""Profile catalog 測試 — core/agents/profile_catalog.py（impl plan Task A1）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.agents.profile_catalog import (
    CAPABILITY_TOOL_MAP,
    CATALOG_VERSION,
    ProfileCatalog,
    load_catalog,
)


@pytest.fixture
def catalog() -> ProfileCatalog:
    return load_catalog()


class TestYAMLCatalog:
    def test_loads_four_official_profiles(self, catalog):
        ids = {p.id for p in catalog.list_profiles()}
        assert {
            "general_research",
            "finance_markets",
            "people_projects",
            "onchain_security",
        } <= ids

    def test_every_profile_has_required_fields(self, catalog):
        for profile in catalog.list_profiles():
            assert profile.id
            assert profile.version
            assert profile.display_name
            assert profile.default_action_policy in ("read_only", "confirm_actions")
            assert profile.default_analysis_mode in ("quick", "verified", "research")
            assert profile.allowed_tool_categories, profile.id

    def test_finance_markets_has_market_categories(self, catalog):
        cats = set(catalog.require("finance_markets").allowed_tool_categories)
        assert {"crypto_basic", "technical", "tw_stock", "us_stock", "forex"} <= cats

    def test_people_projects_capabilities(self, catalog):
        caps = set(catalog.require("people_projects").capabilities)
        assert {
            "discover",
            "project_detail",
            "comments_summary",
            "person_lookup",
            "advanced_funds",
        } == caps

    def test_catalog_version_defined(self):
        assert CATALOG_VERSION


class TestValidation:
    def test_validate_agent_ids_splits_valid_and_unknown(self, catalog):
        valid, unknown = catalog.validate_agent_ids(
            ["people_projects", "nonexistent", "general_research", "people_projects"]
        )
        assert valid == ["people_projects", "general_research"]
        assert unknown == ["nonexistent"]

    def test_validate_agent_ids_empty(self, catalog):
        assert catalog.validate_agent_ids([]) == ([], [])

    def test_all_capabilities_includes_capability_map_keys(self, catalog):
        caps = catalog.all_capabilities()
        assert set(CAPABILITY_TOOL_MAP.keys()) <= caps


class TestCapabilityToolMap:
    def test_advanced_funds_maps_to_balance_and_txns(self):
        assert set(CAPABILITY_TOOL_MAP["advanced_funds"]) == {
            "get_user_balances",
            "get_txns",
        }

    def test_discover_maps_to_search_tools(self):
        assert set(CAPABILITY_TOOL_MAP["discover"]) == {
            "search_projects",
            "recommend_projects",
            "list_causes",
        }

    def test_tools_for_capabilities_union(self, catalog):
        names = catalog.tools_for_capabilities(["discover", "person_lookup"])
        assert {"search_projects", "search_users", "get_user"} <= names


class TestFailSoft:
    def test_invalid_yaml_file_skipped(self, tmp_path: Path):
        (tmp_path / "good.yaml").write_text(
            "id: test_profile\ndisplay_name: Test\n", encoding="utf-8"
        )
        (tmp_path / "broken.yaml").write_text("{ not valid yaml: ", encoding="utf-8")
        catalog = load_catalog(tmp_path)
        ids = {p.id for p in catalog.list_profiles()}
        assert "test_profile" in ids
        assert catalog.get("broken") is None

    def test_missing_general_research_uses_fallback(self, tmp_path: Path):
        (tmp_path / "other.yaml").write_text(
            "id: other_profile\n", encoding="utf-8"
        )
        catalog = load_catalog(tmp_path)
        fallback = catalog.get("general_research")
        assert fallback is not None
        assert fallback.version == "0.0.0-fallback"

    def test_duplicate_id_rejected(self, tmp_path: Path):
        (tmp_path / "a.yaml").write_text("id: dup\n", encoding="utf-8")
        (tmp_path / "b.yaml").write_text("id: dup\n", encoding="utf-8")
        catalog = load_catalog(tmp_path)
        assert catalog.get("dup") is not None  # 一個存活即可，不 crash
