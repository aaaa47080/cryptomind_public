from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
I18N_DIR = WEB / "js" / "i18n"


def flatten(data: dict, prefix: str = "") -> dict[str, str]:
    items: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            items.update(flatten(value, full_key))
        else:
            items[full_key] = value
    return items


def load_translations(name: str) -> dict[str, str]:
    payload = json.loads((I18N_DIR / name).read_text(encoding="utf-8"))
    return flatten(payload)


def collect_i18n_keys() -> set[str]:
    keys: set[str] = set()
    html_pattern = re.compile(r'data-i18n="([^"]+)"')
    js_pattern = re.compile(r"""I18n\.t\(\s*['"]([^'"]+)['"]""")

    for path in list(WEB.rglob("*.html")) + list((WEB / "js").rglob("*.js")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        keys.update(html_pattern.findall(text))
        keys.update(js_pattern.findall(text))

    # Drop dynamic-concatenation prefixes: when JS builds a key at runtime via
    # I18n.t('forexBanks.' + symbol, { defaultValue: ... }), the regex captures
    # only the trailing-dot string literal ('forexBanks.'). A real i18n key
    # never ends with a dot, so these prefixes are false positives, not missing
    # translations. The runtime defaultValue fallback handles unknown keys.
    return {k for k in keys if not k.endswith(".")}


def test_translation_files_parse_and_match():
    zh = load_translations("zh-TW.json")
    en = load_translations("en.json")
    assert set(zh) == set(en)


def test_four_language_files_have_identical_key_sets():
    """四語 key 結構必須完全一致（治理規則，DANNY 2026-08-20）。

    不一致代表：某 key 翻譯漏了一兩語、或文本寫死在前端根本沒進 i18n
    體系。任何新增 key 必須四語同步（zh-TW / zh-CN / en / ru）。
    """
    base = load_translations("zh-TW.json")
    for name in ("zh-CN.json", "en.json", "ru.json"):
        other = load_translations(name)
        missing = set(base) - set(other)
        extra = set(other) - set(base)
        assert not missing and not extra, (
            f"{name} 與 zh-TW key 不一致：缺 {sorted(missing)[:5]}、"
            f"多 {sorted(extra)[:5]}——新 key 必須四語同步新增"
        )


def test_all_referenced_i18n_keys_exist():
    zh = load_translations("zh-TW.json")
    en = load_translations("en.json")
    used = collect_i18n_keys()
    assert used - set(zh) == set()
    assert used - set(en) == set()


def test_scam_tracker_pages_load_i18n_assets():
    pages = [
        WEB / "scam-tracker" / "index.html",
        WEB / "scam-tracker" / "detail.html",
        WEB / "scam-tracker" / "submit.html",
    ]
    for page in pages:
        text = page.read_text(encoding="utf-8")
        # PR #498 起，共用層（含 i18n.js）由 classic-compat-app module 載入，
        # 頁面不再直接引用 /static/js/i18n.js（classic 引用 module 檔會語法錯誤）
        assert "/static/js/classic-compat-app.js" in text
        assert "i18next" in text  # i18next CDN（classic-compat 的 i18n 依賴）
        assert "/static/scam-tracker/js/scam-tracker-i18n.js" in text
        assert "lang-toggle-label" in text
