"""導覽偏好契約測試——「前往板塊沒反應」修復（2026-08-24 DANNY 回報）。

兩個事實鎖定：
1. chat / settings 為 locked（不可在 Customize 取消）——chat 是核心 UX
   （訪客模式只有 chat；「新對話」需要 switchTab('chat') 到達）。
   locked 項每次 loadPreferences 自動修復回 enabledItems。
2. executeTabSwitch 不再有 customize 閘門——此前目標 tab 未啟用時
   靜默改跳第一個啟用 tab（通常=目前的 chat），導致訊息裡的
   「前往 X 板塊」nav chip、#hash deep-link、新對話全部「點了沒反應」。
   Customize 只控制底部導覽列按鈕，不是存取控制。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


class TestNavConfigContract:
    def test_chat_and_settings_are_locked(self):
        src = (ROOT / "web/js/nav-config.js").read_text(encoding="utf-8")
        for tab_id in ("chat", "settings"):
            block = src.split(f"id: '{tab_id}',", 1)[1].split("},", 1)[0]
            assert "locked: true" in block, f"{tab_id} 應為 locked（不可取消）"

    def test_locked_items_healed_on_every_load(self):
        src = (ROOT / "web/js/nav-config.js").read_text(encoding="utf-8")
        assert "Ensure locked items are always included" in src
        # 修復在版本 migration 之外（每次載入都跑，舊用戶自動恢復 chat）
        assert "i.locked" in src


class TestSpaGateRemoved:
    def test_execute_tab_switch_no_longer_redirects_disabled_tabs(self):
        src = (ROOT / "web/js/spa.js").read_text(encoding="utf-8")
        assert "redirecting to first enabled tab" not in src, (
            "customize 閘門應已移除——停用 tab 的切換不得靜默彈回"
        )
        assert "NavPreferences.isItemEnabled(tabId)" not in src, (
            "executeTabSwitch 不得以 NavPreferences 擋 tab 存取"
        )

    def test_nav_chip_still_wired_to_switch_tab(self):
        chip = (ROOT / "web/js/chat-analysis.js").read_text(encoding="utf-8")
        delegator = (ROOT / "web/js/click-delegator.js").read_text(encoding="utf-8")
        assert 'data-click="switchTab"' in chip
        assert "action === 'switchTab'" in delegator


class TestNavPreferencesBehavior:
    """行為測試：node 載入 nav-config.js（mock window/localStorage）。"""

    @pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
    def test_chat_cannot_be_disabled_and_is_healed(self, tmp_path):
        script = tmp_path / "nav_behavior.mjs"
        script.write_text(
            """
const store = {};
globalThis.window = globalThis;
globalThis.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
};
const { NavPreferences } = await import(process.argv[2]);

// 1) locked：chat/settings 不可停用
if (NavPreferences.canDisableItem('chat')) throw new Error('chat should be locked');
if (NavPreferences.canDisableItem('settings')) throw new Error('settings should be locked');
if (NavPreferences.setItemEnabled('chat', false)) throw new Error('disable chat should fail');

// 2) healing：舊用戶（停用過 chat）載入後 chat 自動回到 enabledItems
store['userNavPreferences'] = JSON.stringify({
    version: NavPreferences.PREFERENCES_VERSION,
    enabledItems: ['crypto', 'twstock', 'usstock'],  // 沒有 chat
});
NavPreferences._cache = null;
const prefs = NavPreferences.loadPreferences();
if (!prefs.enabledItems.includes('chat')) {
    throw new Error('locked chat should be healed into enabledItems');
}
console.log('OK');
""",
            encoding="utf-8",
        )
        # package.json 無 "type": "module"——.js 會被 node 當 CJS，
        # 複製成 .mjs 才能 import（nav-config.js 無相對 import，可安全複製）
        module_copy = tmp_path / "nav-config.mjs"
        module_copy.write_text(
            (ROOT / "web/js/nav-config.js").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        result = subprocess.run(
            ["node", str(script), str(module_copy)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout
