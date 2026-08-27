"""Seed 稽核測試 — 防止「bootstrap 註冊了但 DB catalog 沒 seed」的工具遺漏。

背景（O-1 修復）：38 個 runtime 工具曾被 _TOOLS_SEED 遺漏，導致
get_allowed_tools（SQL JOIN tools_catalog）永遠不回傳它們 → LLM 拿不到
→ commodity/forex/global/macro 全套 + TON 錢包工具形同不存在。
本測試把差集檢查固化，任何「新註冊但沒 seed」的工具會立刻紅。

「內部機制」工具（load_skill/remember/clarify 等）是 agent 內部調度，
不走 DB catalog，需在此白名單。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

#: agent 內部調度工具（不走 DB catalog，不應 seed）
_INTERNAL_TOOLS = {
    "clarify",
    "cryptomind",
    "get_current_time_taipei",
    "load_knowledge",
    "load_skill",
    "news",
    "remember",
    "technical",
    "tool_result_retrieve",
}


def _bootstrap_registered() -> set[str]:
    boot = (_REPO / "core" / "agents" / "bootstrap.py").read_text(encoding="utf-8")
    return set(re.findall(r'name="([a-z_0-9]+)"', boot))


def _seeded_tools() -> set[str]:
    tools = (_REPO / "core" / "database" / "tools.py").read_text(encoding="utf-8")
    return set(re.findall(r'"tool_id": "([a-z_0-9]+)"', tools))


def _agent_default_tools() -> set[str]:
    tools = (_REPO / "core" / "database" / "tools.py").read_text(encoding="utf-8")
    # _AGENT_DEFAULT_TOOLS 是 dict 定義；用大括號配對抓整個 dict body。
    start = tools.index('_AGENT_DEFAULT_TOOLS: Dict[str, List[str]] = {')
    open_idx = tools.index("{", start)
    depth = 0
    end = open_idx
    for i in range(open_idx, len(tools)):
        if tools[i] == "{":
            depth += 1
        elif tools[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    block = tools[open_idx : end + 1]
    return set(re.findall(r'"([a-z_0-9]+)"', block))


@pytest.mark.unit
class TestToolSeedAudit:
    def test_all_registered_tools_are_seeded(self):
        """bootstrap 註冊的每個真工具都必須在 _TOOLS_SEED（否則 LLM 拿不到）。"""
        missing = _bootstrap_registered() - _seeded_tools() - _INTERNAL_TOOLS
        assert not missing, (
            "這些工具在 bootstrap 註冊但未進 _TOOLS_SEED，LLM 永遠拿不到：\n"
            + "\n".join(f"  - {m}" for m in sorted(missing))
        )

    def test_all_seeded_tools_in_agent_defaults(self):
        """每個「bootstrap 有註冊」的 seed 工具都要在 _AGENT_DEFAULT_TOOLS。

        註：純 seed 但 bootstrap 未註冊的工具（如 cryptopanic_news_source——
        aggregate_news 的金鑰來源，非獨立工具）不需要 agent 授權。
        """
        registered = _bootstrap_registered()
        not_authorized = (_seeded_tools() & registered) - _agent_default_tools()
        assert not not_authorized, (
            "這些工具在 bootstrap 註冊且已 seed，但不在任何 agent 的 default 清單"
            "（無 agent_tool_permissions，LLM 拿不到）：\n"
            + "\n".join(f"  - {m}" for m in sorted(not_authorized))
        )

    def test_ton_wallet_tools_present(self):
        """O-1 重點：TON 錢包 3 件套必須在 seed 與 cryptomind agent。"""
        seeded = _seeded_tools()
        for tool in ("get_ton_balance", "get_ton_jetton_balances", "get_my_wallet_overview"):
            assert tool in seeded, f"{tool} 不在 _TOOLS_SEED"

        tools = (_REPO / "core" / "database" / "tools.py").read_text(encoding="utf-8")
        cryptomind_block = tools[
            tools.index('"cryptomind": [') : tools.index('"commodity": [')
        ]
        for tool in ("get_ton_jetton_balances", "get_my_wallet_overview"):
            assert tool in cryptomind_block, f"{tool} 不在 cryptomind agent 清單"


@pytest.mark.unit
class TestSeedToolsCatalogRuns:
    """實測 seed_tools_catalog 流程（mock DB connection，不依賴真 PostgreSQL）。

    本機無 DB 時也能驗證：seed 真的會把每個工具 INSERT 進 catalog、
    每個 agent 授權 INSERT 進 permissions——不是只有檔案存在。
    """

    def test_seed_inserts_all_tools(self, monkeypatch):
        from unittest.mock import MagicMock

        from core.database import tools as tools_module
        from core.database.tools import _TOOLS_SEED, seed_tools_catalog

        executed = []
        cursor = MagicMock()
        conn = MagicMock()

        def fake_execute(sql, params=None):
            executed.append((sql, params))

        cursor.execute.side_effect = fake_execute
        conn.cursor.return_value = cursor

        monkeypatch.setattr(tools_module, "get_connection", lambda: conn)

        seed_tools_catalog()

        # 1. 每個 seed 工具都 INSERT 進 tools_catalog
        insert_sqls = [sql for sql, _ in executed if "INSERT INTO tools_catalog" in sql]
        assert len(insert_sqls) == len(_TOOLS_SEED), (
            f"tools_catalog INSERT 數 {len(insert_sqls)} != seed 數 {len(_TOOLS_SEED)}"
        )

        # 2. 新補的工具（O-1）真的有被 INSERT（參數在 params 裡，不在 SQL 字串）
        inserted_ids = []
        for sql, params in executed:
            if "INSERT INTO tools_catalog" in sql and isinstance(params, (tuple, list)):
                inserted_ids.append(params[0])  # 第一個參數是 tool_id
        for tool in (
            "get_ton_jetton_balances",
            "get_my_wallet_overview",
            "get_commodity_price",
            "global_stock_price",
            "get_market_indices",
        ):
            assert tool in inserted_ids, (
                f"{tool} 沒被 seed_tools_catalog INSERT（O-1 修復漏了）"
            )

        # 3. agent_tool_permissions 有寫入（至少 cryptomind 的授權）
        perm_sqls = [sql for sql, _ in executed if "INSERT INTO agent_tool_permissions" in sql]
        assert perm_sqls, "agent_tool_permissions 完全沒有 INSERT（agent 授權沒 seed）"

        # 4. deactivate 檢查有跑（不在 seed 的舊工具會被關）
        deact_sqls = [sql for sql, _ in executed if "is_active = FALSE" in sql]
        assert deact_sqls, "obsolete 工具 deactivate 沒執行"
