"""Unit tests for TON Connect verification (login proof + payment)."""

import base64
import hashlib
import struct
import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException

import api.ton_verification as tv

# Wallets sign window.location.host (host[:port]) — mirror that, not .hostname.
DOMAIN = urlparse(tv.TON_MANIFEST_URL).netloc
RAW_ADDR = "0:ef8c3844675dbc124b5b481acae025abc35c534dbc78a23959fab17638e4b61f"


def _make_signed_proof(priv, payload, ts, domain=DOMAIN, address=RAW_ADDR):
    wc, h = tv._parse_raw_address(address)
    message = (
        b"ton-proof-item-v2/"
        + struct.pack(">i", wc)
        + h
        + struct.pack("<I", len(domain.encode()))
        + domain.encode()
        + struct.pack("<Q", ts)
        + payload.encode()
    )
    full = b"\xff\xff" + b"ton-connect" + hashlib.sha256(message).digest()
    signed = hashlib.sha256(full).digest()
    return base64.b64encode(priv.sign(signed)).decode()


@pytest.fixture
def keypair():
    priv = Ed25519PrivateKey.generate()
    pub_hex = (
        priv.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )
    return priv, pub_hex


# --- proof payload (nonce) ---------------------------------------------------


@pytest.mark.unit
def test_payload_roundtrip_valid():
    p = tv.generate_ton_proof_payload()
    assert tv._check_payload(p) is True


@pytest.mark.unit
def test_payload_tampered_rejected():
    p = tv.generate_ton_proof_payload()
    tampered = p[:-1] + ("0" if p[-1] != "0" else "1")
    assert tv._check_payload(tampered) is False


@pytest.mark.unit
def test_payload_expired_rejected(monkeypatch):
    p = tv.generate_ton_proof_payload()
    # advance time beyond TTL (capture real now first to avoid recursion)
    future = time.time() + tv.TON_PROOF_PAYLOAD_TTL + 10
    monkeypatch.setattr(tv.time, "time", lambda: future)
    assert tv._check_payload(p) is False


# --- ton_proof signature -----------------------------------------------------


@pytest.mark.unit
def test_verify_ton_proof_valid(keypair):
    priv, pub_hex = keypair
    ts = int(time.time())
    payload = tv.generate_ton_proof_payload()
    sig = _make_signed_proof(priv, payload, ts)
    # should not raise
    tv.verify_ton_proof(
        address=RAW_ADDR,
        public_key=pub_hex,
        domain=DOMAIN,
        timestamp=ts,
        payload=payload,
        signature=sig,
    )


@pytest.mark.unit
def test_verify_ton_proof_accepts_host_with_port(keypair, monkeypatch):
    """Regression (25617cd): wallets sign ``window.location.host``, which
    includes the port on non-default ports (e.g. ``localhost:8080``). The
    server compared against ``urlparse().hostname`` — which drops the port —
    so every such login was 401'd with "TON proof domain mismatch".
    """
    priv, pub_hex = keypair
    monkeypatch.setattr(tv, "TON_MANIFEST_URL", "http://localhost:8080")
    host_with_port = "localhost:8080"
    ts = int(time.time())
    payload = tv.generate_ton_proof_payload()
    sig = _make_signed_proof(priv, payload, ts, domain=host_with_port)
    # Must not raise: this is the exact host the browser reports.
    tv.verify_ton_proof(
        address=RAW_ADDR,
        public_key=pub_hex,
        domain=host_with_port,
        timestamp=ts,
        payload=payload,
        signature=sig,
    )


@pytest.mark.unit
def test_verify_ton_proof_rejects_wrong_port(keypair, monkeypatch):
    """A proof signed for a different port is a different origin — reject it."""
    priv, pub_hex = keypair
    monkeypatch.setattr(tv, "TON_MANIFEST_URL", "http://localhost:8080")
    wrong = "localhost:9999"
    ts = int(time.time())
    payload = tv.generate_ton_proof_payload()
    sig = _make_signed_proof(priv, payload, ts, domain=wrong)
    with pytest.raises(HTTPException) as e:
        tv.verify_ton_proof(
            address=RAW_ADDR,
            public_key=pub_hex,
            domain=wrong,
            timestamp=ts,
            payload=payload,
            signature=sig,
        )
    assert e.value.status_code == 401


@pytest.mark.unit
def test_verify_ton_proof_bad_signature(keypair):
    priv, pub_hex = keypair
    ts = int(time.time())
    payload = tv.generate_ton_proof_payload()
    bad = base64.b64encode(priv.sign(b"x" * 32)).decode()
    with pytest.raises(HTTPException) as e:
        tv.verify_ton_proof(
            address=RAW_ADDR,
            public_key=pub_hex,
            domain=DOMAIN,
            timestamp=ts,
            payload=payload,
            signature=bad,
        )
    assert e.value.status_code == 401


@pytest.mark.unit
def test_verify_ton_proof_rejects_signature_for_another_domain(keypair):
    """A valid proof for an attacker-controlled origin cannot log in here."""
    priv, pub_hex = keypair
    ts = int(time.time())
    payload = tv.generate_ton_proof_payload()
    attacker_domain = "attacker.example"
    sig = _make_signed_proof(priv, payload, ts, domain=attacker_domain)

    with pytest.raises(HTTPException) as e:
        tv.verify_ton_proof(
            address=RAW_ADDR,
            public_key=pub_hex,
            domain=attacker_domain,
            timestamp=ts,
            payload=payload,
            signature=sig,
        )

    assert e.value.status_code == 401


@pytest.mark.unit
def test_verify_ton_proof_stale_timestamp(keypair):
    priv, pub_hex = keypair
    ts = int(time.time()) - tv.TON_PROOF_TIMESTAMP_WINDOW - 100
    payload = tv.generate_ton_proof_payload()
    sig = _make_signed_proof(priv, payload, ts)
    with pytest.raises(HTTPException):
        tv.verify_ton_proof(
            address=RAW_ADDR,
            public_key=pub_hex,
            domain=DOMAIN,
            timestamp=ts,
            payload=payload,
            signature=sig,
        )


@pytest.mark.unit
def test_verify_ton_proof_forged_payload(keypair):
    priv, pub_hex = keypair
    ts = int(time.time())
    payload = "1.deadbeef.notavalidsig"  # never issued by us
    sig = _make_signed_proof(priv, payload, ts)
    with pytest.raises(HTTPException):
        tv.verify_ton_proof(
            address=RAW_ADDR,
            public_key=pub_hex,
            domain=DOMAIN,
            timestamp=ts,
            payload=payload,
            signature=sig,
        )


# --- order token -------------------------------------------------------------


@pytest.mark.unit
def test_order_token_roundtrip():
    order = tv.create_ton_order("user-1", "premium_monthly", 0.3)
    decoded = tv.verify_ton_order_token(order["order_token"], "user-1")
    assert decoded["p"] == "premium_monthly"
    assert decoded["a"] == 0.3
    assert decoded["c"] == order["comment"]


@pytest.mark.unit
def test_order_token_binds_custom_receiver():
    receiver = "0:" + "a" * 64
    order = tv.create_ton_order(
        "user-1", "tip", 0.3, receiving_address=receiver
    )
    decoded = tv.verify_ton_order_token(order["order_token"], "user-1")

    assert decoded["r"] == receiver
    assert order["receiving_address"] == receiver


@pytest.mark.unit
def test_order_token_rejects_non_wallet_receiver():
    with pytest.raises(HTTPException) as exc:
        tv.create_ton_order("user-1", "tip", 0.3, receiving_address="tg_user_123")

    assert exc.value.status_code == 400


@pytest.mark.unit
def test_order_token_wrong_user():
    order = tv.create_ton_order("user-1", "premium_monthly", 0.3)
    with pytest.raises(HTTPException) as e:
        tv.verify_ton_order_token(order["order_token"], "attacker")
    assert e.value.status_code == 403


@pytest.mark.unit
def test_order_token_tampered(monkeypatch):
    monkeypatch.setenv(
        "JWT_SECRET_KEY", "ton-verification-test-secret-stable-across-suite"
    )
    order = tv.create_ton_order("user-1", "premium_monthly", 0.3)
    b64, sig = order["order_token"].split(".")
    # 竄改 sig 最後一字元。原寫法 sig[:-1] + "0" 有 1/16 機率原結尾就是 "0"
    # → 沒真的改變 sig → compare_digest 通過 → DID NOT RAISE（機率性 fail）。
    # 改成保證替換成「與原字元不同」的字元。
    last = sig[-1]
    flipped = "1" if last == "0" else "0"
    with pytest.raises(HTTPException):
        tv.verify_ton_order_token(f"{b64}.{sig[:-1]}{flipped}", "user-1")


# --- payment verification (mocked toncenter) ---------------------------------


def _mock_toncenter(transactions):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "result": transactions}
    client = AsyncMock()
    client.get.return_value = resp
    ctx = AsyncMock()
    ctx.__aenter__.return_value = client
    return ctx


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_payment_match():
    comment = "cmabc123"
    tx = {
        "in_msg": {"value": "300000000", "message": comment, "source": "0:aaa"},
        "transaction_id": {"hash": "HASH123"},
        "utime": 1700000000,
    }
    with patch.object(tv.httpx, "AsyncClient", return_value=_mock_toncenter([tx])):
        result = await tv.verify_ton_payment(comment, 0.3)
    assert result["tx_hash"] == "HASH123"
    assert result["value_ton"] == 0.3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_payment_scans_signed_receiver():
    receiver = "0:" + "b" * 64
    ctx = _mock_toncenter([])
    with patch.object(tv.httpx, "AsyncClient", return_value=ctx):
        with pytest.raises(HTTPException):
            await tv.verify_ton_payment("cmabc123", 0.3, receiving_address=receiver)

    assert ctx.__aenter__.return_value.get.await_args.kwargs["params"]["address"] == receiver


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_payment_amount_too_low():
    comment = "cmabc123"
    tx = {
        "in_msg": {"value": "100000000", "message": comment},  # 0.1 TON < 0.3
        "transaction_id": {"hash": "H"},
    }
    with patch.object(tv.httpx, "AsyncClient", return_value=_mock_toncenter([tx])):
        with pytest.raises(HTTPException) as e:
            await tv.verify_ton_payment(comment, 0.3)
    assert e.value.status_code == 400


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_payment_no_match():
    tx = {"in_msg": {"value": "300000000", "message": "other"}}
    with patch.object(tv.httpx, "AsyncClient", return_value=_mock_toncenter([tx])):
        with pytest.raises(HTTPException) as e:
            await tv.verify_ton_payment("cmabc123", 0.3)
    assert e.value.status_code == 400
