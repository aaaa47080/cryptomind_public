from pathlib import Path

TON_AUTH_SOURCE = Path("web/js/ton-auth.js").read_text(encoding="utf-8")


def test_ton_login_waits_for_auth_manager_before_creating_backend_session():
    """A restored TON proof may arrive before auth.js has finished loading."""
    complete_login = TON_AUTH_SOURCE.split(
        "async function _completeLoginFromWallet(w)", 1
    )[1].split("// ---- 登入主流程 ----", 1)[0]

    assert "await _waitForAuthManager" in complete_login
    assert complete_login.index("await _waitForAuthManager") < complete_login.index(
        "AppAPI.post('/api/user/ton-login'"
    )


def test_apply_ton_session_reports_failure_when_auth_manager_is_unavailable():
    apply_session = TON_AUTH_SOURCE.split("function _applyTonSession", 1)[1].split(
        "// ---- Telegram 原生登入", 1
    )[0]

    assert "if (!A) return false" in apply_session
    assert "return true" in apply_session
