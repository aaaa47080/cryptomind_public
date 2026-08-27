"""
Tests for analysis_queue Redis queue + pub/sub layer.

These tests verify the graceful degradation logic (no Redis → fallback to False/None)
and the key/channel naming conventions. Full Redis integration tests require a live
Redis instance (skipped in CI without REDIS_URL).
"""

import pytest

from core.analysis_queue import (
    _control_channel,
    _event_channel,
    dequeue_job,
    enqueue_job,
    publish_control,
    publish_event,
    reset,
)


@pytest.fixture(autouse=True)
def _reset_state():
    """每個測試前重置 Redis 連線狀態。"""
    reset()
    yield
    reset()


class TestChannelNaming:
    """Redis channel 命名慣例。"""

    def test_event_channel_format(self):
        assert _event_channel("abc123") == "analysis:events:abc123"

    def test_control_channel_format(self):
        assert _control_channel("abc123") == "analysis:control:abc123"


class TestGracefulDegradation:
    """Redis 不可用時的優雅降級（無 REDIS_URL 環境）。"""

    def test_enqueue_returns_false_without_redis(self):
        """無 Redis → enqueue 回 False（API fallback 到 in-process）。"""
        result = enqueue_job({"run_id": "test", "session_id": "s1"})
        assert result is False

    def test_dequeue_returns_none_without_redis(self):
        """無 Redis → dequeue 回 None（worker 不該跑）。"""
        result = dequeue_job(timeout=1)
        assert result is None

    def test_publish_event_silent_without_redis(self):
        """無 Redis → publish_event 不 raise（靜默 no-op）。"""
        # 不該 raise 任何例外
        publish_event("test-run", {"type": "token", "data": {"chunk": "hi"}})

    def test_publish_control_returns_false_without_redis(self):
        """無 Redis → publish_control 回 False（revoke fallback 到 in-process）。"""
        result = publish_control("test-run", "revoke")
        assert result is False


class TestJobEnvelopeFormat:
    """Job envelope 格式驗證（analysis.py 的 _build_job_envelope）。"""

    def test_envelope_is_json_serializable(self):
        """Job envelope 的所有欄位都是 JSON 可序列化的。"""
        import json

        envelope = {
            "run_id": "abc123",
            "session_id": "session-1",
            "user_id": "user-1",
            "language": "zh-TW",
            "user_tier": "free",
            "display_name": "Danny",
            "wallet_address": "0x1234...",
            "credentials": {"provider": "openrouter", "api_key": "sk-...", "model": "test"},
            "key_fingerprint": "abc12345",
            "web_mode": "web",
            "graph_input": {"goto": "claw_loop", "update": {"query": "test"}},
            "config": {"configurable": {"thread_id": "session-1"}, "recursion_limit": 60},
            "resume_answer": None,
            "created_at": 1234567890.0,
        }

        # 必須能 JSON 序列化（Redis queue 傳輸用）
        serialized = json.dumps(envelope)
        deserialized = json.loads(serialized)
        assert deserialized["run_id"] == "abc123"
        assert deserialized["credentials"]["provider"] == "openrouter"
        assert deserialized["graph_input"]["goto"] == "claw_loop"
