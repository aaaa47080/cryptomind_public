"""
test_guest_access.py — 訪客模式測試（設計：docs/plans/2026-08-19-guest-access-design.md）

涵蓋：
- 簽名 cookie 發放與驗證（無效簽章換新）
- 免登入可問（mock LLM）、回應含剩餘額度
- 每日限量（GUEST_DAILY_QUESTIONS）→ 429
- 輸入防護（敏感詞 filter → 400）
- 平台金鑰缺失 → 503 優雅關閉
- 高風險功能 fail-closed：未登入存取需授權端點仍 401（TEST_MODE 關閉下）
"""

from __future__ import annotations

import pytest

from api.routers import guest as guest_router
from core import shared_cache

pytestmark = pytest.mark.unit


class _FakeResp:
    def __init__(self, content: str):
        self.content = content


class _FakeClient:
    def __init__(self, content: str = "BTC is consolidating. Not financial advice."):
        self._content = content
        self.calls = []

    def invoke(self, messages, max_tokens=None):
        self.calls.append(messages)
        return _FakeResp(self._content)


@pytest.fixture(autouse=True)
def _reset_cache():
    shared_cache.reset()
    from api.middleware.rate_limit import limiter

    limiter.reset()  # 每測重置 slowapi 限額（同一測試 IP 共用計數）
    # 測試環境無 Redis → shared_cache 是靜默 no-op，計數落在模組級
    # fallback dict；全站計數 key 固定（非 per-guest），不清會跨測試殘留
    guest_router._local_quota.clear()
    guest_router._local_global.clear()
    yield
    shared_cache.reset()
    limiter.reset()
    guest_router._local_quota.clear()
    guest_router._local_global.clear()


@pytest.fixture
def mock_llm(monkeypatch):
    """mock 平台 LLM + 跳過行情快照（不碰網路）。"""
    fake = _FakeClient()
    monkeypatch.setattr(
        guest_router.LLMClientFactory,
        "create_client",
        lambda *a, **kw: fake,
    )
    async def _snap():
        return ""

    monkeypatch.setattr(guest_router, "_safe_snapshot", _snap)
    return fake


async def _post(client, message="What is BTC outlook today?", language="en"):
    return await client.post(
        "/api/guest/analyze",
        json={"message": message, "language": language},
    )


class TestGuestCookie:
    async def test_first_visit_issues_signed_cookie(self, client, mock_llm):
        resp = await _post(client)
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "guest_id=" in set_cookie
        assert "HttpOnly" in set_cookie

    async def test_reply_contains_quota(self, client, mock_llm):
        resp = await _post(client)
        assert resp.status_code == 200
        data = resp.json()
        assert "reply" in data and data["reply"]
        assert data["limit"] == 3
        assert data["remaining"] == 2  # 預設 3，用掉 1

    async def test_tampered_cookie_gets_new_identity(self, client, mock_llm, monkeypatch):
        monkeypatch.setenv("GUEST_DAILY_QUESTIONS", "1")
        # 偽造簽名 → 伺服器應視為新訪客（換發），而非沿用計量
        client.cookies.set("guest_id", "0" * 32 + ".deadbeefdeadbeef")
        resp1 = await _post(client)
        assert resp1.status_code == 200
        # 偽造 id 已被換發 → 新身分，額度重置（仍是 1 → remaining 0）
        assert resp1.json()["remaining"] == 0


class TestGuestQuotaEndpoint:
    """GET /api/guest/quota — banner 顯示用額度查詢（不扣額、不碰 LLM）。"""

    async def test_quota_returns_limit_without_consuming(self, client):
        # 不給 mock_llm：此端點不應碰 LLM（碰了會因平台金鑰缺失而 503）
        resp = await client.get("/api/guest/quota")
        assert resp.status_code == 200
        assert resp.json() == {"limit": 3, "remaining": 3}
        assert "guest_id=" in resp.headers.get("set-cookie", "")

    async def test_quota_reflects_env_and_usage(self, client, mock_llm, monkeypatch):
        monkeypatch.setenv("GUEST_DAILY_QUESTIONS", "2")
        q1 = (await client.get("/api/guest/quota")).json()
        assert q1 == {"limit": 2, "remaining": 2}
        assert (await _post(client)).status_code == 200
        q2 = (await client.get("/api/guest/quota")).json()
        assert q2 == {"limit": 2, "remaining": 1}  # 查詢本身不扣額，只有 analyze 扣


class TestGuestModelFallback:
    """免費模型 fallback 鏈（GUEST_LLM_FALLBACK_MODELS，建議 #5）。

    防護：OpenRouter 免費線日額（帳號級）耗盡或模型退場（404/429）時，
    訪客模式不應整個掛掉——自動切鏈上的備用模型。
    """

    async def test_fallback_on_rate_limit(self, client, mock_llm, monkeypatch):
        monkeypatch.setenv("GUEST_LLM_FALLBACK_MODELS", "backup/model:free")

        bad = _FakeClient()
        bad.invoke = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("429 rate limit exceeded for model")
        )
        clients = iter([bad, _FakeClient()])
        monkeypatch.setattr(
            guest_router.LLMClientFactory,
            "create_client",
            lambda *a, **kw: next(clients),
        )
        resp = await _post(client)
        assert resp.status_code == 200
        assert resp.json()["reply"]

    async def test_all_models_exhausted_502(self, client, mock_llm, monkeypatch):
        monkeypatch.setenv("GUEST_LLM_FALLBACK_MODELS", "backup/model:free")

        class _Boom:
            def invoke(self, *a, **kw):
                raise RuntimeError("429 rate limit exceeded")

        monkeypatch.setattr(
            guest_router.LLMClientFactory, "create_client", lambda *a, **kw: _Boom()
        )
        resp = await _post(client)
        assert resp.status_code == 502

    async def test_transient_error_no_fallback(self, client, mock_llm, monkeypatch):
        """非額度類錯誤（如模型輸出壞掉）不該燒備用鏈——直接 502。"""
        monkeypatch.setenv("GUEST_LLM_FALLBACK_MODELS", "backup/model:free")

        class _Weird:
            def invoke(self, *a, **kw):
                raise RuntimeError("connection reset by peer")

        monkeypatch.setattr(
            guest_router.LLMClientFactory, "create_client", lambda *a, **kw: _Weird()
        )
        resp = await _post(client)
        assert resp.status_code == 502


class TestGuestGlobalCap:
    """全站訪客每日總量（GUEST_GLOBAL_DAILY_CAP，預設 300，0=關）。

    防護目標：清 cookie 換新 guest_id 繞過每人限量、輪替 IP 打爆平台
    OpenRouter 免費線日額 → 全站計數做硬上限，跨所有訪客共享。
    """

    async def test_global_cap_binds_all_visitors(self, client, mock_llm, monkeypatch):
        monkeypatch.setenv("GUEST_GLOBAL_DAILY_CAP", "2")
        assert (await _post(client)).status_code == 200
        # 換新訪客身分（偽簽章 → 伺服器換發新 guest_id，個人額度全新）
        client.cookies.set("guest_id", "0" * 32 + ".deadbeef")
        assert (await _post(client)).status_code == 200
        # 第三個訪客：個人額度全新，但全站額度已用罄 → 429（capacity）
        client.cookies.set("guest_id", "1" * 32 + ".deadbeef")
        resp = await _post(client)
        assert resp.status_code == 429
        assert "capacity" in resp.json()["detail"]

    async def test_global_cap_zero_disables(self, client, mock_llm, monkeypatch):
        monkeypatch.setenv("GUEST_GLOBAL_DAILY_CAP", "0")
        for _ in range(3):  # 個人預設 3 全部放行，全站上限關閉不擋
            assert (await _post(client)).status_code == 200


class TestGuestQuota:
    async def test_daily_limit_enforced(self, client, mock_llm, monkeypatch):
        monkeypatch.setenv("GUEST_DAILY_QUESTIONS", "2")
        assert (await _post(client)).status_code == 200
        assert (await _post(client)).status_code == 200
        resp3 = await _post(client)
        assert resp3.status_code == 429
        assert "Guest daily limit" in resp3.json()["detail"]

    async def test_zero_disables_guest(self, client, mock_llm, monkeypatch):
        monkeypatch.setenv("GUEST_DAILY_QUESTIONS", "0")
        resp = await _post(client)
        assert resp.status_code == 429


class TestGuestInputGuard:
    async def test_sensitive_word_rejected(self, client, mock_llm):
        resp = await _post(client, message="加我 wechat 私聊")
        assert resp.status_code == 400

    async def test_empty_message_rejected(self, client, mock_llm):
        resp = await client.post("/api/guest/analyze", json={"message": ""})
        assert resp.status_code == 422  # pydantic min_length


class TestGuestUnavailable:
    async def test_missing_platform_key_503(self, client, monkeypatch):
        def _boom(*a, **kw):
            raise ValueError("Missing API Key for provider 'openrouter'.")

        monkeypatch.setattr(
            guest_router.LLMClientFactory, "create_client", _boom
        )
        resp = await _post(client)
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["detail"]


class TestFailClosed:
    async def test_protected_endpoint_still_401_for_anonymous(
        self, client, monkeypatch
    ):
        """高風險端點不因訪客模式放寬：關閉 TEST_MODE 後匿名仍 401。"""
        import core.config as cfg

        monkeypatch.setattr(cfg, "TEST_MODE", False)
        # alerts 為需授權的使用者資料端點
        resp = await client.get("/api/alerts")
        assert resp.status_code == 401

    async def test_guest_cannot_access_user_memory(self, client, monkeypatch):
        import core.config as cfg

        monkeypatch.setattr(cfg, "TEST_MODE", False)
        resp = await client.get("/api/memory")
        assert resp.status_code in (401, 403, 404)  # 404=路由未掛，仍非放行
