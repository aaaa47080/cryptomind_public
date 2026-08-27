"""Tests for the /tonconnect-manifest.json endpoint.

Regression guard for the login outage caused by 337467b: the manifest started
being derived from ``request.base_url``, but Zeabur terminates TLS and talks
plain HTTP to the container, so every URL in the manifest came back as
``http://`` on an HTTPS site. Wallets reject such a manifest after the QR scan
and the user can never finish logging in.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api_server import app

    return TestClient(app)


def _manifest(client, **headers):
    res = client.get("/tonconnect-manifest.json", headers=headers)
    assert res.status_code == 200
    return res.json()


def test_manifest_uses_forwarded_proto_when_behind_a_tls_proxy(client):
    """X-Forwarded-Proto wins over the plain-HTTP connection to the container."""
    data = _manifest(
        client,
        **{"X-Forwarded-Proto": "https", "Host": "cryptomind-ton.zeabur.app"},
    )

    for key in ("url", "iconUrl", "termsOfUseUrl", "privacyPolicyUrl"):
        assert data[key].startswith("https://cryptomind-ton.zeabur.app"), key


def test_manifest_handles_multi_hop_forwarded_proto(client):
    """A proxy chain sends a comma-separated list; the first hop is the client's."""
    data = _manifest(
        client,
        **{"X-Forwarded-Proto": "https, http", "Host": "cryptomind-ton.zeabur.app"},
    )

    assert data["url"] == "https://cryptomind-ton.zeabur.app"


def test_manifest_keeps_request_host(client):
    """Host-based fallback (the point of 337467b) still works."""
    data = _manifest(
        client, **{"X-Forwarded-Proto": "https", "Host": "staging.example.com"}
    )

    assert data["url"] == "https://staging.example.com"


def test_manifest_stays_http_for_local_dev(client):
    """No proxy header → plain http localhost keeps working for dev."""
    data = _manifest(client, **{"Host": "localhost:8080"})

    assert data["url"] == "http://localhost:8080"


def test_manifest_forces_https_in_production_without_forwarded_proto(
    client, monkeypatch
):
    """保底層：production 少了 X-Forwarded-Proto 也不能發出 http manifest。"""
    import api_server

    monkeypatch.setattr(api_server, "_IS_PRODUCTION", True)

    data = _manifest(client, **{"Host": "cryptomind-ton.zeabur.app"})

    assert data["url"] == "https://cryptomind-ton.zeabur.app"
