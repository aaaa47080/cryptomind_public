"""
TON Connect verification

Two responsibilities:
1. Login ownership   — verify a `ton_proof` (ed25519) proving the user controls
   the wallet they claim, following the TON Connect ton-proof-item-v2 spec.
2. Payment           — verify an on-chain transfer to our receiving wallet via
   the toncenter API (amount + unique comment), without trusting the client.

No new third-party dependency: ed25519 verification uses `cryptography`
(already pinned), nonce/order binding uses HMAC with the JWT secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import struct
import time
from typing import Any, Dict
from urllib.parse import urlparse

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException

from api.utils import logger
from core.config import (
    TON_AMOUNT_TOLERANCE,
    TON_IS_TESTNET,
    TON_MANIFEST_URL,
    TON_RECEIVING_ADDRESS,
    TONCENTER_API_BASE,
    TONCENTER_API_KEY,
)

# ttl windows
TON_PROOF_PAYLOAD_TTL = 15 * 60  # nonce valid for 15 minutes
TON_PROOF_TIMESTAMP_WINDOW = 15 * 60  # wallet signature freshness
TON_ORDER_TTL = 30 * 60  # payment order valid for 30 minutes

# On mainnet we recommend binding the proof public key to the on-chain wallet.
# On testnet wallets are frequently undeployed, so default off there.
TON_PROOF_REQUIRE_ONCHAIN_PUBKEY = (
    os.getenv("TON_PROOF_REQUIRE_ONCHAIN_PUBKEY", "false").lower() == "true"
)

_FRIENDLY_TON_ADDRESS = re.compile(r"^[A-Za-z0-9_-]{48}$")
_RAW_TON_ADDRESS = re.compile(r"^-?\d+:[0-9a-fA-F]{64}$")


def _validate_payment_receiver(receiver: str) -> str:
    if not isinstance(receiver, str) or not (
        _FRIENDLY_TON_ADDRESS.fullmatch(receiver)
        or _RAW_TON_ADDRESS.fullmatch(receiver)
    ):
        raise HTTPException(status_code=400, detail="Invalid TON payment receiver")
    return receiver


def _secret() -> bytes:
    secret = os.getenv("JWT_SECRET_KEY", "")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="Server configuration error: JWT_SECRET_KEY not set",
        )
    return secret.encode()


def _sign(data: bytes) -> str:
    return hmac.new(_secret(), data, hashlib.sha256).hexdigest()[:32]


def _expected_ton_proof_domain() -> str:
    """Return the only origin whose TON Connect proofs this server accepts.

    Wallets sign the proof with ``window.location.host`` — the host *with* its
    port whenever the port is non-default (e.g. ``localhost:8080``). We must
    therefore compare against the manifest's ``netloc`` (host[:port]), not
    ``hostname``: ``urlparse().hostname`` drops the port, so a ported dev/staging
    origin would mismatch and 401 every login (regression from commit 25617cd).
    On default ports (443/80) browsers omit the port, so ``netloc`` for a plain
    ``https://cryptomind-ton.zeabur.app`` is just the bare host — prod is
    unaffected.
    """
    parsed = urlparse(TON_MANIFEST_URL)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    is_production = os.getenv("ENVIRONMENT", "development").lower() in {
        "production",
        "prod",
    }
    if not hostname or (is_production and parsed.scheme != "https"):
        raise HTTPException(status_code=500, detail="TON manifest is misconfigured")
    # host[:port] exactly as the browser reports it (strip any userinfo).
    return parsed.netloc.rsplit("@", 1)[-1].rstrip(".").lower()


# ---------------------------------------------------------------------------
# 1. ton_proof — login ownership
# ---------------------------------------------------------------------------


def generate_ton_proof_payload() -> str:
    """Issue a stateless, self-verifying nonce for the wallet to sign."""
    ts = int(time.time())
    rnd = os.urandom(8).hex()
    body = f"{ts}.{rnd}"
    return f"{body}.{_sign(body.encode())}"


def _check_payload(payload: str) -> bool:
    """Validate a payload we previously issued (signature + freshness)."""
    try:
        ts_str, rnd, sig = payload.split(".")
    except (ValueError, AttributeError):
        return False
    body = f"{ts_str}.{rnd}".encode()
    if not hmac.compare_digest(sig, _sign(body)):
        return False
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    return (time.time() - ts) <= TON_PROOF_PAYLOAD_TTL


def _parse_raw_address(address: str) -> tuple[int, bytes]:
    """Parse a raw TON address 'workchain:hex' into (workchain, 32-byte hash)."""
    try:
        wc_str, hash_hex = address.split(":")
        wc = int(wc_str)
        h = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid TON address format")
    if len(h) != 32:
        raise HTTPException(status_code=400, detail="Invalid TON address hash length")
    return wc, h


def verify_ton_proof(
    *,
    address: str,
    public_key: str,
    domain: str,
    timestamp: int,
    payload: str,
    signature: str,
) -> None:
    """
    Verify a TON Connect ton_proof. Raises HTTPException on any failure.

    Reconstructs the signed message per ton-proof-item-v2 and checks the
    ed25519 signature against the wallet public key, plus nonce + freshness.
    """
    # 1. A proof signed for another origin must never be reusable here.
    if domain.rstrip(".").lower() != _expected_ton_proof_domain():
        raise HTTPException(status_code=401, detail="TON proof domain mismatch")

    # 2. our nonce must be one we issued and still fresh
    if not _check_payload(payload):
        raise HTTPException(status_code=401, detail="Invalid or expired proof payload")

    # 3. wallet signature must be recent
    now = int(time.time())
    if abs(now - int(timestamp)) > TON_PROOF_TIMESTAMP_WINDOW:
        raise HTTPException(status_code=401, detail="Proof timestamp out of range")

    wc, addr_hash = _parse_raw_address(address)

    # 4. rebuild the signed message
    #    message = "ton-proof-item-v2/" + wc(int32 BE) + hash(32) +
    #              domain_len(uint32 LE) + domain + ts(uint64 LE) + payload
    domain_bytes = domain.encode()
    message = (
        b"ton-proof-item-v2/"
        + struct.pack(">i", wc)
        + addr_hash
        + struct.pack("<I", len(domain_bytes))
        + domain_bytes
        + struct.pack("<Q", int(timestamp))
        + payload.encode()
    )
    full_message = b"\xff\xff" + b"ton-connect" + hashlib.sha256(message).digest()
    signed_hash = hashlib.sha256(full_message).digest()

    # 5. verify ed25519 signature
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
        pub.verify(base64.b64decode(signature), signed_hash)
    except (InvalidSignature, ValueError, TypeError) as exc:
        logger.warning("ton_proof signature verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid wallet signature")

    # 6. (hardening) bind public key to the on-chain wallet
    if TON_PROOF_REQUIRE_ONCHAIN_PUBKEY:
        _assert_onchain_public_key(address, public_key)

    logger.info("ton_proof verified for address %s", address)


def _assert_onchain_public_key(address: str, public_key: str) -> None:
    """
    Confirm the wallet's on-chain public key matches the proof key by calling
    the wallet's `get_public_key` get-method. If the wallet is not yet deployed
    (common on testnet / before first payment) the check is skipped rather than
    blocking login.
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"{TONCENTER_API_BASE}/runGetMethod",
                params=_with_key({}),
                json={"address": address, "method": "get_public_key", "stack": []},
            )
    except httpx.HTTPError as exc:
        logger.warning("On-chain pubkey check skipped (network error): %s", exc)
        return

    if resp.status_code != 200:
        logger.warning("On-chain pubkey check skipped (status %s)", resp.status_code)
        return

    body = resp.json()
    # exit_code != 0 usually means the account is not deployed yet
    if not body.get("ok") or body.get("result", {}).get("exit_code", -1) != 0:
        logger.info("Wallet %s not deployed; skipping on-chain pubkey bind", address)
        return

    stack = body.get("result", {}).get("stack", [])
    if not stack:
        return
    try:
        onchain_int = int(stack[0][1], 16)  # ["num", "0x..."]
        proof_int = int(public_key, 16)
    except (ValueError, IndexError, TypeError):
        logger.warning("Could not parse on-chain public key for %s", address)
        return

    if onchain_int != proof_int:
        raise HTTPException(
            status_code=401,
            detail="Wallet public key does not match on-chain account",
        )


# ---------------------------------------------------------------------------
# 2. payment order binding (stateless) + on-chain verification
# ---------------------------------------------------------------------------


def create_ton_order(
    user_id: str,
    plan: str,
    amount_ton: float,
    *,
    receiving_address: str | None = None,
) -> Dict[str, Any]:
    """
    Create a payment order bound to a user. The `comment` is what the wallet
    attaches on-chain; the `order_token` lets us re-verify the binding
    statelessly at upgrade time.
    """
    comment = "cm" + os.urandom(9).hex()  # short, unique on-chain memo
    exp = int(time.time()) + TON_ORDER_TTL
    receiver = _validate_payment_receiver(receiving_address or TON_RECEIVING_ADDRESS)
    payload = {
        "u": user_id,
        "p": plan,
        "a": round(float(amount_ton), 9),
        "c": comment,
        "r": receiver,
        "e": exp,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    token = base64.urlsafe_b64encode(raw).decode() + "." + _sign(raw)
    return {
        "comment": comment,
        "order_token": token,
        "amount_ton": payload["a"],
        "receiving_address": receiver,
        "network": "testnet" if TON_IS_TESTNET else "mainnet",
        "expires_at": exp,
    }


def verify_ton_order_token(order_token: str, user_id: str) -> Dict[str, Any]:
    """Verify and decode an order token, ensuring it belongs to `user_id`."""
    try:
        b64, sig = order_token.split(".")
        raw = base64.urlsafe_b64decode(b64)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid order token")
    if not hmac.compare_digest(sig, _sign(raw)):
        raise HTTPException(status_code=400, detail="Order token signature mismatch")
    payload = json.loads(raw)
    if payload.get("u") != user_id:
        raise HTTPException(status_code=403, detail="Order does not belong to user")
    if int(payload.get("e", 0)) < int(time.time()):
        raise HTTPException(status_code=400, detail="Order has expired")
    return payload


def _with_key(params: Dict[str, Any]) -> Dict[str, Any]:
    if TONCENTER_API_KEY:
        params = {**params, "api_key": TONCENTER_API_KEY}
    return params


def _extract_comment(in_msg: Dict[str, Any]) -> str:
    """Pull the text comment from an incoming message (toncenter shape)."""
    # toncenter exposes decoded text comments in `message`; binary in msg_data
    msg = in_msg.get("message")
    if isinstance(msg, str) and msg:
        return msg.strip()
    msg_data = in_msg.get("msg_data") or {}
    if msg_data.get("@type") == "msg.dataText":
        try:
            return base64.b64decode(msg_data.get("text", "")).decode().strip()
        except (ValueError, UnicodeDecodeError):
            return ""
    return ""


async def verify_ton_payment(
    comment: str,
    expected_amount_ton: float,
    *,
    receiving_address: str | None = None,
) -> Dict[str, Any]:
    """
    Confirm an incoming transfer to our receiving wallet carrying `comment`
    with at least `expected_amount_ton`. Returns the matched transaction.

    Does not trust any client-provided hash — scans the chain directly.
    Raises HTTPException if no matching settled transaction is found.
    """
    receiver = _validate_payment_receiver(receiving_address or TON_RECEIVING_ADDRESS)
    expected_nano = int(round(float(expected_amount_ton) * 1e9))
    tolerance_nano = int(round(TON_AMOUNT_TOLERANCE * 1e9))

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{TONCENTER_API_BASE}/getTransactions",
                params=_with_key(
                    {
                        "address": receiver,
                        "limit": 40,
                        "archival": "true",
                    }
                ),
            )
    except httpx.HTTPError as exc:
        logger.error("toncenter request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Unable to reach TON network")

    if resp.status_code != 200:
        logger.error("toncenter returned %s: %s", resp.status_code, resp.text[:200])
        raise HTTPException(status_code=502, detail="TON network verification error")

    body = resp.json()
    if not body.get("ok"):
        raise HTTPException(status_code=502, detail="TON network verification error")

    for tx in body.get("result", []):
        in_msg = tx.get("in_msg") or {}
        if _extract_comment(in_msg) != comment:
            continue
        try:
            value = int(in_msg.get("value", 0))
        except (TypeError, ValueError):
            continue
        if value + tolerance_nano < expected_nano:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Payment amount too low: expected {expected_amount_ton} TON, "
                    f"got {value / 1e9} TON"
                ),
            )
        tx_id = tx.get("transaction_id", {}) or {}
        tx_hash = tx_id.get("hash") or ""
        logger.info("TON payment verified: comment=%s hash=%s", comment, tx_hash[:16])
        return {
            "tx_hash": tx_hash,
            "value_ton": value / 1e9,
            "source": in_msg.get("source", ""),
            "utime": tx.get("utime"),
        }

    raise HTTPException(
        status_code=400,
        detail="No matching payment found yet — please wait for confirmation",
    )
