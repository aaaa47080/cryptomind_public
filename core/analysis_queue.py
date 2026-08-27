"""
analysis_queue.py — 分析任務佇列 + 即時事件管道（Redis）。

把「分析執行」從 API 進程移到獨立 worker 進程，徹底脫離 gunicorn
worker recycle 的威脅。

架構：
    [API]  enqueue_job(envelope)  →  Redis List (analysis:queue)
    [Worker]  dequeue_job()  ←  BRPOP analysis:queue
    [Worker]  publish_event(run_id, event)  →  Redis Pub/Sub (analysis:events:{run_id})
    [API]  async subscribe_events(run_id)  ←  Pub/Sub 訂閱 → SSE yield
    [API]  publish_control(run_id, "revoke")  →  Redis Pub/Sub (analysis:control:{run_id})
    [Worker]  subscribe_control(run_id)  ←  Pub/Sub 訂閱 → cancel task

設計原則（對齊 core/shared_cache.py）：
    1. lazy client，第一次用才連線；連不上只檢查一次。
    2. 優雅降級 —— Redis 不可用時 enqueue 回傳 False，API 自動 fallback
       到 in-process 路徑（現有 event_generator_v4 不刪）。
    3. sync client（worker 端）+ async client（API SSE 端）共用 URL resolver。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional

import orjson

from core.redis_url import resolve_redis_url

logger = logging.getLogger(__name__)

# ── Redis key 前綴 ────────────────────────────────────────────────────────────

_QUEUE_KEY = "analysis:queue"
_EVENT_CHANNEL_PREFIX = "analysis:events:"
_CONTROL_CHANNEL_PREFIX = "analysis:control:"


def _event_channel(run_id: str) -> str:
    return f"{_EVENT_CHANNEL_PREFIX}{run_id}"


def _control_channel(run_id: str) -> str:
    return f"{_CONTROL_CHANNEL_PREFIX}{run_id}"


# ── Sync client（worker 端 + enqueue 用）──────────────────────────────────────

_sync_client: Optional[Any] = None
_sync_checked: bool = False


def _get_sync_client() -> Optional[Any]:
    """回傳可用的 sync Redis client，不可用則回 None（只檢查一次）。"""
    global _sync_client, _sync_checked
    if _sync_checked:
        return _sync_client

    _sync_checked = True
    redis_url, source = resolve_redis_url()
    if not redis_url or redis_url.startswith("memory://"):
        logger.info("[AnalysisQueue] No external Redis — worker dispatch disabled")
        return None

    try:
        import redis as _redis

        _sync_client = _redis.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=35,  # 比 BRPOP timeout(30s) 長，避免 socket 先斷
        )
        _sync_client.ping()
        logger.info("[AnalysisQueue] Sync Redis connected via %s", source)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("[AnalysisQueue] Sync Redis unavailable: %s", exc)
        _sync_client = None

    return _sync_client


# ── Async client（API SSE 端用）───────────────────────────────────────────────

_async_client: Optional[Any] = None
_async_checked: bool = False


async def _get_async_client() -> Optional[Any]:
    """回傳可用的 async Redis client，不可用則回 None。"""
    global _async_client, _async_checked
    if _async_checked:
        return _async_client

    _async_checked = True
    redis_url, source = resolve_redis_url()
    if not redis_url or redis_url.startswith("memory://"):
        return None

    try:
        import redis.asyncio as aioredis

        _async_client = aioredis.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        await _async_client.ping()
        logger.info("[AnalysisQueue] Async Redis connected via %s", source)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("[AnalysisQueue] Async Redis unavailable: %s", exc)
        _async_client = None

    return _async_client


# ── Queue 操作 ────────────────────────────────────────────────────────────────


def enqueue_job(job_envelope: Dict[str, Any]) -> bool:
    """API 端：把分析任務推進 Redis queue。回傳 True 成功、False fallback。"""
    client = _get_sync_client()
    if client is None:
        return False
    try:
        client.lpush(_QUEUE_KEY, orjson.dumps(job_envelope))
        logger.info(
            "[AnalysisQueue] Enqueued job run_id=%s session=%s",
            job_envelope.get("run_id"),
            job_envelope.get("session_id"),
        )
        return True
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("[AnalysisQueue] enqueue failed: %s", exc)
        return False


def dequeue_job(timeout: int = 30) -> Optional[Dict[str, Any]]:
    """Worker 端：阻塞等待 job（BRPOP）。timeout 秒無 job 回 None。"""
    client = _get_sync_client()
    if client is None:
        return None
    try:
        result = client.brpop(_QUEUE_KEY, timeout=timeout)
        if result is None:
            return None
        # result = (key, value)
        return orjson.loads(result[1])
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.error("[AnalysisQueue] dequeue failed: %s", exc)
        return None


# ── 事件發布（worker 端，sync）────────────────────────────────────────────────


def publish_event(run_id: str, event: Dict[str, Any]) -> None:
    """Worker 端：發事件到 pub/sub channel（token / progress / final / done）。"""
    client = _get_sync_client()
    if client is None:
        return
    try:
        client.publish(_event_channel(run_id), orjson.dumps(event))
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("[AnalysisQueue] publish_event failed: %s", exc)


def publish_control(run_id: str, action: str) -> bool:
    """API 端：發控制指令（revoke）到 control channel。回傳 True 成功。"""
    client = _get_sync_client()
    if client is None:
        return False
    try:
        client.publish(_control_channel(run_id), orjson.dumps({"action": action}))
        return True
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("[AnalysisQueue] publish_control failed: %s", exc)
        return False


# ── 事件訂閱（API SSE 端，async）──────────────────────────────────────────────


async def subscribe_events(
    run_id: str, *, timeout: float = 15.0
) -> AsyncIterator[Dict[str, Any]]:
    """API 端：訂閱 run 的事件 channel，yield 解析後的 event dict。

    每次迴圈最多等 timeout 秒。如果 timeout 內無事件，yield 一個 keep-alive
    空事件（呼叫端可以 yield SSE comment）。
    遇到 done/revoked/error 事件後停止迭代。
    """
    client = await _get_async_client()
    if client is None:
        return

    pubsub = client.pubsub()
    await pubsub.subscribe(_event_channel(run_id))
    try:
        while True:
            try:
                msg = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # keep-alive：yield None 讓 SSE generator 發心跳 comment
                yield None
                continue

            if msg is None:
                continue
            if msg.get("type") != "message":
                continue

            data = msg.get("data")
            if data is None:
                continue

            try:
                event = orjson.loads(data)
            except Exception:
                continue

            yield event

            # 終端事件 → 停止
            event_type = event.get("type")
            if event_type in ("done", "revoked", "error"):
                break
    finally:
        try:
            await pubsub.unsubscribe(_event_channel(run_id))
        except Exception:
            pass


# ── 控制訂閱（worker 端，async，背景 task）────────────────────────────────────


async def listen_for_control(
    run_id: str, on_revoke: Any
) -> None:
    """Worker 端：背景監聽 control channel，收到 revoke 時呼叫 on_revoke()。

    on_revoke 是一個 callable（通常 cancel invoke_task）。
    """
    client = await _get_async_client()
    if client is None:
        return

    pubsub = client.pubsub()
    await pubsub.subscribe(_control_channel(run_id))
    try:
        while True:
            msg = await asyncio.wait_for(
                pubsub.get_message(ignore_subscribe_messages=True),
                timeout=1.0,
            )
            if msg and msg.get("type") == "message":
                try:
                    data = orjson.loads(msg.get("data", b"{}"))
                    if data.get("action") == "revoke":
                        logger.info(
                            "[AnalysisQueue] Received revoke for run_id=%s", run_id
                        )
                        on_revoke()
                        break
                except Exception:
                    continue
    except asyncio.TimeoutError:
        pass
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            await pubsub.unsubscribe(_control_channel(run_id))
        except Exception:
            pass


# ── 重置（測試用）─────────────────────────────────────────────────────────────


def reset() -> None:
    """重置連線狀態（主要給測試用）。"""
    global _sync_client, _sync_checked, _async_client, _async_checked
    _sync_client = None
    _sync_checked = False
    _async_client = None
    _async_checked = False
