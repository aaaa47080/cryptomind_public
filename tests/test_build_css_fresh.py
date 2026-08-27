"""tailwind-built.css 新鮮度檢查（2026-08-20，#507 事故的產物）。

web/css/tailwind-built.css 是 repo 內直接部署的編譯產物——HTML/JS 新增
的 Tailwind class 若未重編，部署後樣式靜默失效（#507：md:self-start 不在
部署 CSS 裡、nav 容器蓋滿畫面）。本測試重跑 build:css 並比對位元組，
不一致即 fail——在本地套件與 CI（帳單修復後）都會把關。

無 npm 環境（罕見）跳過，避免誤傷。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / 'web' / 'css' / 'tailwind-built.css'


def test_tailwind_built_css_is_fresh():
    if shutil.which('npm') is None:
        pytest.skip('npm 不可用，跳過編譯新鮮度檢查')

    before = BUILT.read_bytes()
    subprocess.run(
        ['npm', 'run', 'build:css'],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=180,
    )
    after = BUILT.read_bytes()

    assert before == after, (
        'web/css/tailwind-built.css 與 tailwind-src.css 不同步——'
        '新增了 Tailwind class 但未重編。請跑 `npm run build:css` 並 commit 產物，'
        '否則部署後新 class 樣式靜默失效（見 PR #507 事故）。'
    )
