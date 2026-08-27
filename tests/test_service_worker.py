"""Tests for the /sw.js endpoint (service worker serving).

Service worker 必須在根路徑 /sw.js 服務，才能以 scope '/' 控制全站
（包含根路徑的 index.html）。但 vite-plugin-pwa 因 base: '/static/'
會把 sw.js 產到 /static/sw.js，預設 scope 只有 /static/。所以後端另外
開 /sw.js 路由，服務同一份檔案並送 Service-Worker-Allowed: / header，
讓瀏覽器允許 register('/sw.js', { scope: '/' })。
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api_server import app

    return TestClient(app)


def test_sw_js_returns_service_worker_allowed_header(client):
    """允許 SW 控制比 /sw.js 所在路徑更廣的 scope（/）。"""
    res = client.get("/sw.js")
    # sw.js 檔案可能不存在於本機（未 build），端點仍要回應並送 header
    assert res.status_code in (200, 404)
    if res.status_code == 200:
        assert res.headers.get("service-worker-allowed") == "/"


def test_sw_js_not_served_with_no_store(client, tmp_path, monkeypatch):
    """SW 更新檢查要能拿到新版，不能被 no-store/no-cache 擋住更新流程。"""
    # 建一個假 sw.js，讓 _resolve_sw_js_path 回傳它
    import api_server

    sw_path = tmp_path / "sw.js"
    sw_path.write_text("// stub sw", encoding="utf-8")
    monkeypatch.setattr(api_server, "_resolve_sw_js_path", lambda: str(sw_path))

    res = client.get("/sw.js")
    assert res.status_code == 200
    cc = res.headers.get("cache-control", "")
    # 允許 no-cache（每次重驗）但不能 no-store（會破壞 SW 更新檢查）
    assert "no-store" not in cc.lower()


def test_sw_js_serves_actual_file_when_present(client, tmp_path, monkeypatch):
    """檔案存在時回 200 + JS MIME + Service-Worker-Allowed。"""
    import api_server

    sw_path = tmp_path / "sw.js"
    sw_path.write_text("self.addEventListener('install',()=>{});", encoding="utf-8")
    monkeypatch.setattr(api_server, "_resolve_sw_js_path", lambda: str(sw_path))

    res = client.get("/sw.js")
    assert res.status_code == 200
    ct = res.headers.get("content-type", "")
    assert "javascript" in ct
    assert res.headers.get("service-worker-allowed") == "/"


def test_workbox_js_served_at_root_when_present(client, tmp_path, monkeypatch):
    """generateSW 的 sw.js 以 ./workbox-<hash> 引用；根路徑必須服務此檔，否則 SW 載入失敗。"""
    import api_server

    wb_path = tmp_path / "workbox-9c191d2f.js"
    wb_path.write_text("self.workbox={};", encoding="utf-8")
    monkeypatch.setattr(
        api_server, "_resolve_workbox_path", lambda fn: str(wb_path)
    )

    res = client.get("/workbox-9c191d2f.js")
    assert res.status_code == 200
    assert "javascript" in res.headers.get("content-type", "")
    assert "no-store" not in res.headers.get("cache-control", "").lower()


def test_workbox_js_404_when_not_built(client, monkeypatch):
    """未 build 時回 404，讓前端註冊腳本的 try/catch 能忽略。"""
    import api_server

    monkeypatch.setattr(api_server, "_resolve_workbox_path", lambda fn: None)

    res = client.get("/workbox-deadbeef.js")
    assert res.status_code == 404
