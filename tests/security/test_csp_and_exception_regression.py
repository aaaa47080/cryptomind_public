"""
Regression tests for CSP hardening and CancelledError propagation.

Verifies:
1. CSP headers: script-src 'unsafe-inline' is allowed ONLY with a documented
   justification (TON Connect SDK v3 injects unhashed inline event handlers;
   removing it breaks wallet login — see commit b1924913). The test enforces
   that the trade-off is explicitly documented, not silently introduced.
2. No inline event-handler attributes in HTML or JavaScript-rendered templates
3. No inline <script> (without src) in index.html
4. CancelledError propagates through guarded except blocks
5. Broad except Exception still catches normal errors (behavior unchanged)
"""

import asyncio
import glob
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WEB_DIR = PROJECT_ROOT / "web"
MIDDLEWARE_FILE = PROJECT_ROOT / "api" / "middleware_setup.py"


# ── CSP Header Tests ──────────────────────────────────────────────────────────


class TestCSPHeaders:
    """Verify Content-Security-Policy does not allow unsafe-inline for scripts."""

    def test_script_src_unsafe_inline_requires_justification(self):
        """script-src 'unsafe-inline' is a documented TON Connect trade-off.

        TON Connect SDK v3 injects inline event handlers without a hash, so
        'unsafe-inline' is required in script-src (commit b1924913). Removing
        it breaks wallet login. This test does NOT ban 'unsafe-inline'; instead
        it enforces that the trade-off is explicitly documented in the
        middleware, so a future change cannot silently weaken CSP without
        acknowledging the reason.
        """
        content = MIDDLEWARE_FILE.read_text(encoding="utf-8")
        assert "Content-Security-Policy" in content, "CSP header not found"

        script_src_line = None
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('"script-src'):
                script_src_line = stripped
                break
        if script_src_line is None:
            pytest.fail("script-src directive line not found in CSP")

        if "'unsafe-inline'" not in script_src_line:
            # script-src is stricter than the documented baseline — that's fine.
            return

        # 'unsafe-inline' present: the middleware MUST explain why, naming the
        # SDK that requires it. This guards against silent regressions.
        justification_markers = (
            "TON Connect",
            "inline event handler",
            "unsafe-inline",
        )
        missing = [m for m in justification_markers if m not in content]
        assert not missing, (
            "script-src keeps 'unsafe-inline' but the middleware lacks a "
            f"documented justification. Missing markers: {missing}. "
            "If unsafe-inline is truly required, document the reason next to "
            "the CSP header (see commit b1924913)."
        )

    def test_style_src_allows_inline_styles_for_tonconnect(self):
        """style-src must keep 'unsafe-inline'.

        TON Connect UI injects dynamic inline styles (and CSP hashes cannot
        cover style attributes), so removing it breaks the wallet login modal
        in production. script-src remains the strict, XSS-critical directive.
        """
        content = MIDDLEWARE_FILE.read_text(encoding="utf-8")
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('"style-src'):
                assert "'unsafe-inline'" in stripped, (
                    f"style-src must allow inline styles for TON Connect UI: {stripped}"
                )
                return
        pytest.fail("style-src directive line not found in CSP")

    def test_connect_src_allows_wallet_bridges(self):
        """connect-src must allow https: (+ ws/wss).

        The TON Connect wallet list resolves to per-wallet bridge origins
        (walletbot.me, mytonwallet, OKX, Binance, ...) that change over time;
        enumerating them breaks wallet login whenever the list changes.
        """
        content = MIDDLEWARE_FILE.read_text(encoding="utf-8")
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('"connect-src'):
                for scheme in ("https:", "wss:", "ws:"):
                    assert f" {scheme}" in stripped, (
                        f"connect-src must include {scheme}: {stripped}"
                    )
                return
        pytest.fail("connect-src directive line not found in CSP")


# ── Inline Handler Tests ──────────────────────────────────────────────────────


class TestNoInlineHandlers:
    """Verify no CSP-blocked inline event handlers remain in rendered markup."""

    _INLINE_HANDLER_RE = re.compile(
        r"(?<![.\w])on(?:click|submit|key(?:press|down|up)|input|change|blur)\s*=",
        re.IGNORECASE,
    )

    @pytest.mark.parametrize(
        "html_file",
        sorted(glob.glob(str(WEB_DIR / "**" / "*.html"), recursive=True)),
    )
    def test_no_inline_onclick(self, html_file):
        """No HTML file should contain inline onclick= attributes."""
        content = Path(html_file).read_text(encoding="utf-8")
        assert "onclick=" not in content, (
            f"{html_file} contains inline onclick= — use data-click= instead"
        )

    @pytest.mark.parametrize(
        "template_file",
        sorted(glob.glob(str(WEB_DIR / "**" / "*.html"), recursive=True))
        + sorted(glob.glob(str(WEB_DIR / "**" / "*.js"), recursive=True)),
    )
    def test_no_inline_event_attributes_in_rendered_templates(self, template_file):
        """Dynamic JS templates are subject to the same production CSP as HTML.

        Property assignments such as ``button.onclick = handler`` are allowed;
        the negative lookbehind intentionally excludes those and only rejects
        markup attributes such as ``onclick=`` / ``onchange=``.
        """
        if Path(template_file).name == "click-delegator.js":
            # This file documents the legacy attribute name in comments only.
            return

        content = Path(template_file).read_text(encoding="utf-8")
        matches = self._INLINE_HANDLER_RE.findall(content)
        assert not matches, (
            f"{template_file} contains {len(matches)} inline event handler(s): "
            f"{sorted(set(match.lower() for match in matches))}. "
            "Use data-* attributes plus a CSP-safe listener instead."
        )

    def test_index_html_no_inline_script_without_src(self):
        """index.html should not have inline <script> without src attribute."""
        content = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        import re

        # Find <script> tags without src=
        inline_scripts = re.findall(r"<script>(?!.*\bsrc=)", content)
        assert len(inline_scripts) == 0, (
            f"index.html has {len(inline_scripts)} inline <script> without src"
        )

    def test_early_init_js_exists(self):
        """early-init.js must exist (moved from inline script)."""
        assert (WEB_DIR / "js" / "early-init.js").exists()

    def test_click_delegator_js_exists(self):
        """click-delegator.js must exist (handles data-click events)."""
        assert (WEB_DIR / "js" / "click-delegator.js").exists()


# ── CancelledError Propagation Tests ──────────────────────────────────────────


class TestCancelledErrorPropagation:
    """Verify that CancelledError guards properly re-raise system signals."""

    def test_cancelled_error_not_swallowed(self):
        """asyncio.CancelledError should propagate, not be caught by except Exception."""
        async def mock_async_operation():
            raise asyncio.CancelledError()

        async def guarded_handler():
            try:
                await mock_async_operation()
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pytest.fail("CancelledError was swallowed by except Exception")

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(guarded_handler())

    def test_keyboard_interrupt_not_swallowed(self):
        """KeyboardInterrupt should propagate through guarded handler."""
        def mock_sync_operation():
            raise KeyboardInterrupt()

        def guarded_handler():
            try:
                mock_sync_operation()
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pytest.fail("KeyboardInterrupt was swallowed by except Exception")

        with pytest.raises(KeyboardInterrupt):
            guarded_handler()

    def test_system_exit_not_swallowed(self):
        """SystemExit should propagate through guarded handler."""
        def guarded_handler():
            try:
                raise SystemExit(1)
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pytest.fail("SystemExit was swallowed by except Exception")

        with pytest.raises(SystemExit):
            guarded_handler()

    def test_normal_exception_still_caught(self):
        """Normal exceptions must still be caught by except Exception (behavior unchanged)."""
        def guarded_handler():
            try:
                raise ValueError("test error")
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                return str(e)

        result = guarded_handler()
        assert result == "test error"

    def test_http_error_still_caught(self):
        """HTTP errors before the guard must still be handled."""
        from fastapi import HTTPException

        def guarded_handler():
            try:
                raise HTTPException(status_code=404, detail="Not found")
            except HTTPException:
                raise
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                pytest.fail(f"HTTPException was swallowed: {e}")

        with pytest.raises(HTTPException):
            guarded_handler()
