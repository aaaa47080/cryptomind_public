"""Tests for the /manifest.webmanifest endpoint (PWA installability).

跟 /tonconnect-manifest.json 共用同一套 base-URL 修復邏輯，因為兩者面對
同一個 Zeabur proxy 陷阱：TLS 在 proxy 層終止，容器收到的是純 HTTP，
gunicorn 的 forwarded_allow_ips 預設只信 127.0.0.1 → request.base_url 是
http://。PWA 的 start_url / scope / icons 若發出 http://，安裝提示與
iOS「加到主畫面」會出問題（與 tonconnect 登入斷線同根因）。
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api_server import app

    return TestClient(app)


def _manifest(client, **headers):
    res = client.get("/manifest.webmanifest", headers=headers)
    assert res.status_code == 200
    return res


def test_manifest_returns_correct_mime_type(client):
    """nosniff 已開，MIME 必須是 application/manifest+json，否則瀏覽器拒收。"""
    res = _manifest(client, **{"Host": "localhost:8080"})
    assert "manifest+json" in res.headers.get("content-type", "")


def test_manifest_has_required_pwa_fields(client):
    """可安裝 PWA 必備欄位齊全。"""
    data = _manifest(client, **{"Host": "localhost:8080"}).json()
    for key in (
        "name",
        "short_name",
        "description",
        "start_url",
        "scope",
        "display",
        "theme_color",
        "background_color",
        "icons",
    ):
        assert key in data, key
    assert data["display"] in ("standalone", "fullscreen", "minimal-ui")


def test_manifest_icons_include_192_512_and_maskable(client):
    """Chrome 安裝提示需要 192 + 512；maskable 確保 Android 自適應圖示。"""
    data = _manifest(client, **{"Host": "localhost:8080"}).json()
    icons = data["icons"]
    sizes = {i["sizes"] for i in icons}
    assert "192x192" in sizes
    assert "512x512" in sizes
    # 至少有一個 maskable purpose
    assert any("maskable" in i.get("purpose", "") for i in icons)


def test_manifest_uses_forwarded_proto_when_behind_a_tls_proxy(client):
    """X-Forwarded-Proto 勝過容器內的純 HTTP 連線。"""
    data = _manifest(
        client,
        **{"X-Forwarded-Proto": "https", "Host": "cryptomind-ton.zeabur.app"},
    ).json()

    assert data["start_url"].startswith("https://cryptomind-ton.zeabur.app")
    assert data["scope"].startswith("https://cryptomind-ton.zeabur.app")
    for icon in data["icons"]:
        assert icon["src"].startswith("https://cryptomind-ton.zeabur.app"), icon


def test_manifest_handles_multi_hop_forwarded_proto(client):
    """proxy chain 給逗號分隔清單，第一跳才是 client 真實協定。"""
    data = _manifest(
        client,
        **{"X-Forwarded-Proto": "https, http", "Host": "cryptomind-ton.zeabur.app"},
    ).json()

    assert data["start_url"].startswith("https://")


def test_manifest_stays_http_for_local_dev(client):
    """本機無 proxy header → 維持 http，開發不受影響。"""
    data = _manifest(client, **{"Host": "localhost:8080"}).json()

    assert data["start_url"].startswith("http://localhost:8080")
    assert data["scope"] == "http://localhost:8080/"


def test_manifest_forces_https_in_production_without_forwarded_proto(
    client, monkeypatch
):
    """保底：production 缺 X-Forwarded-Proto 也絕不發 http manifest。"""
    import api_server

    monkeypatch.setattr(api_server, "_IS_PRODUCTION", True)

    data = _manifest(client, **{"Host": "cryptomind-ton.zeabur.app"}).json()

    assert data["start_url"].startswith("https://cryptomind-ton.zeabur.app")
