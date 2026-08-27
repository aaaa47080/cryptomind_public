"""
Pytest configuration and fixtures
"""

import os
from unittest.mock import AsyncMock

os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
for _key in list(os.environ):
    if _key.startswith("POSTGRESQL_") or _key == "POSTGRES_DB":
        os.environ.pop(_key)
os.environ["REDIS_URL"] = "memory://"
for _key in list(os.environ):
    if _key.startswith("REDIS_") and _key != "REDIS_URL":
        os.environ.pop(_key)
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing-1234567890")
os.environ.setdefault("TEST_MODE", "true")
os.environ.setdefault("TEST_MODE_CONFIRMATION", "I_UNDERSTAND_THE_RISKS")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("ENVIRONMENT", "development")


import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app():
    from api_server import app

    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers():
    from api.deps import create_access_token

    token = create_access_token(data={"sub": "test-user-001"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    return {"X-Admin-Key": os.getenv("ADMIN_API_KEY", "test-admin-key")}


@pytest.fixture
def mock_llm_client():
    return AsyncMock()


@pytest.fixture(autouse=True)
def _isolate_security_monitor(tmp_path, monkeypatch):
    """把 SecurityMonitor 的儲存路徑隔離到暫存目錄，避免測試汙染 repo。

    根因：core/security_monitor.py 的 get_security_monitor() 用模組級單例，
    預設寫死相對路徑 data/security_events.jsonl。某些測試（如達 auth 失敗閾值）
    會觸發 log_security_event → 真實寫檔。本 fixture 讓每次測試都用 tmp 路徑，
    並在結束後清除單例，確保跨測試不殘留。
    """
    import core.security_monitor as sm

    tmp_file = tmp_path / "security_events.jsonl"
    # 注入臨時單例，避免 get_security_monitor() 建立寫死路徑的預設單例
    sm._global_monitor = sm.SecurityMonitor(storage_path=str(tmp_file))
    try:
        yield
    finally:
        sm._global_monitor = None
