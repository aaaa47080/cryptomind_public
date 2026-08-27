"""Tests for forum tip payment (TON Connect)."""

import pytest

from api.routers.forum.models import CreateTipRequest


class TestCreateTipRequestModel:
    def test_order_fields_optional(self):
        req = CreateTipRequest(amount=1.0)
        assert req.order_token is None
        assert req.comment is None
        assert req.tx_hash is None
        assert req.amount == 1.0

    def test_order_fields_set(self):
        req = CreateTipRequest(order_token="tok.abc", comment="cm123", amount=5.0)
        assert req.order_token == "tok.abc"
        assert req.comment == "cm123"
        assert req.amount == 5.0

    def test_tx_hash_fallback(self):
        req = CreateTipRequest(amount=1.0, tx_hash="tx_abc")
        assert req.tx_hash == "tx_abc"
        assert req.amount == 1.0


class TestTipEndpoint:
    def test_tip_router_has_record_payment_helper(self):
        import api.routers.forum.tips as tips_mod

        # TON tip flow records dedup via _record_tip_payment (keyed on comment)
        assert hasattr(tips_mod, "_record_tip_payment")
        assert callable(tips_mod._record_tip_payment)

    def test_tip_router_has_ton_order_endpoint(self):
        """The TON order endpoint for tips must be registered."""
        from api.routers.forum.tips import router

        paths = [r.path for r in router.routes]
        assert any("ton-order" in p for p in paths)

    def test_create_tip_request_requires_amount(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CreateTipRequest()

    def test_create_tip_request_accepts_ton_order(self):
        req = CreateTipRequest(amount=1.0, order_token="tok.abc", comment="cm123")
        assert req.order_token == "tok.abc"
        assert req.comment == "cm123"


class TestTipOrderRequestModel:
    def test_amount_optional(self):
        from api.routers.forum.models import TipOrderRequest

        req = TipOrderRequest()
        assert req.amount is None

    def test_amount_set(self):
        from api.routers.forum.models import TipOrderRequest

        req = TipOrderRequest(amount=0.1)
        assert req.amount == 0.1
