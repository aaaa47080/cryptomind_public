"""Tests for premium membership upgrade endpoint."""

from unittest.mock import patch

import pytest
from slowapi.errors import RateLimitExceeded

from api.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from api.routers.premium import UpgradeRequest


def _create_test_app():
    """Create a FastAPI test app with limiter configured."""
    from fastapi import FastAPI

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    return app


@pytest.fixture(autouse=True)
def _set_test_mode_false(monkeypatch):
    monkeypatch.setenv("TEST_MODE", "false")


def _make_app_with_deps(premium_router):
    """Create a test FastAPI app with mocked auth dependency."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(premium_router)

    app.dependency_overrides[premium_router.dependencies[0].dependency] = lambda: {
        "user_id": "test-user-1"
    }

    return app, TestClient(app)


class TestUpgradeEndpoint:
    """Tests for the /upgrade endpoint logic (inspect-based, no TestClient)."""

    def test_upgrade_endpoint_requires_ton_order_in_production(self):
        import inspect

        import api.routers.premium as pm

        source = inspect.getsource(pm.upgrade_to_premium)
        assert "order_token" in source
        assert "comment" in source
        assert "TEST_MODE" in source
        assert "not TEST_MODE" in source or "if not TEST_MODE" in source

    def test_upgrade_endpoint_validates_plan(self):
        import inspect

        import api.routers.premium as pm

        source = inspect.getsource(pm.upgrade_to_premium)
        assert "Invalid plan" in source
        assert "PLAN_MONTHS" in source


class TestPricingEndpoint:
    """Tests for the /pricing endpoint."""

    def test_returns_pricing_data(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import api.routers.premium as pm

        app = FastAPI()
        app.include_router(pm.router)

        client = TestClient(app)

        # 定價 v3：USD 錨定（monthly 12 / yearly 108）+ 動態 TON 換算，無 floor。
        # 此測試直接 mock _resolve_premium_ton_amount 回 6.0，驗證 endpoint 串接。
        with patch(
            "api.routers.premium._resolve_premium_ton_amount",
            return_value=6.0,
        ):
            response = client.get("/api/premium/pricing")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "premium" in data["pricing"]
        # USD 錨定價
        assert data["pricing"]["premium"]["monthly"] == 12.0
        assert data["pricing"]["premium"]["yearly"] == 108.0
        # 動態 TON 金額（mock 6.0）
        assert data["ton"]["prices"]["premium_monthly"] == 6.0


class TestUpgradeRequestModel:
    """Tests for UpgradeRequest model."""

    def test_ton_order_fields_optional(self):
        req = UpgradeRequest(
            plan="premium_monthly",
            tx_hash="tx_abc",
        )
        assert req.order_token is None
        assert req.comment is None
        assert req.tx_hash == "tx_abc"

    def test_ton_order_fields_can_be_set(self):
        req = UpgradeRequest(
            plan="premium_yearly",
            order_token="tok.abc",
            comment="cm123",
            tx_hash="tx_abc",
        )
        assert req.order_token == "tok.abc"
        assert req.comment == "cm123"
        assert req.tx_hash == "tx_abc"

    def test_default_plan_is_monthly(self):
        req = UpgradeRequest()
        assert req.plan == "premium_monthly"
        assert req.months == 1


class TestResolvePremiumTonAmount:
    """定價 v3：USD 錨定 + 動態 TON 換算（無 floor，DANNY 決策 #5）。"""

    def test_no_floor_when_ton_surges(self):
        """定價 v3（純 USD 錨定）：TON 暴漲（$5）→ 12/5=2.4 TON，不再有 floor 擋住。"""
        from api.routers.premium import _resolve_premium_ton_amount

        with patch(
            "core.tools.crypto_modules.ton_price.get_ton_usd_price",
            return_value=5.0,
        ):
            assert _resolve_premium_ton_amount("premium_monthly") == 2.4
            assert _resolve_premium_ton_amount("premium_yearly") == 21.6

    def test_dynamic_compute_when_ton_drops(self):
        """TON 暴跌（$0.5）→ 12/0.5=24 TON（高於 floor，照算）。"""
        from api.routers.premium import _resolve_premium_ton_amount

        with patch(
            "core.tools.crypto_modules.ton_price.get_ton_usd_price",
            return_value=0.5,
        ):
            assert _resolve_premium_ton_amount("premium_monthly") == 24.0

    def test_fallback_when_price_source_fails(self):
        """價格來源失敗（None）→ fallback 靜態 TON_PAYMENT_PRICES（不掛）。

        注意：fallback 讀 module 級 TON_PAYMENT_PRICES（可能被 .env 覆寫），
        測試要 patch 靜態值才穩定（本機 .env 有 0.3 測試殘留）。
        """
        from api.routers.premium import _resolve_premium_ton_amount

        with patch(
            "api.routers.premium.TON_PAYMENT_PRICES",
            {"premium_monthly": 6.0, "premium_yearly": 54.0,
             "create_post": 0.1, "tip": 0.1},
        ), patch(
            "core.tools.crypto_modules.ton_price.get_ton_usd_price",
            return_value=None,
        ):
            assert _resolve_premium_ton_amount("premium_monthly") == 6.0
            assert _resolve_premium_ton_amount("premium_yearly") == 54.0
