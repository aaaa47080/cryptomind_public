"""
Analysis Worker — 獨立進程，從 Redis queue 取分析任務並執行。

徹底脫離 gunicorn worker recycle 威脅：分析跑在這個獨立進程裡，
gunicorn 怎麼 recycle 都不影響正在跑的分析。

啟動：python -m scripts.analysis_worker（Dockerfile.analysis-worker 的 CMD）
環境變數：DATABASE_URL、REDIS_URL（與 API 服務共用同一個 Zeabur binding）

循環：
    while True:
        job = dequeue_job(timeout=30)  # BRPOP analysis:queue
        if job:
            asyncio.run(_run_job(job))
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import traceback
from typing import Any, Dict, Optional

logger = logging.getLogger("analysis_worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

# 分析超時（跟 API 端 ANALYSIS_TIMEOUT_SECONDS 對齊）
_ANALYSIS_TIMEOUT = int(os.getenv("ANALYSIS_TIMEOUT_SECONDS", "3600"))


async def _run_job(job: Dict[str, Any]) -> None:
    """執行單一分析任務（從 Redis queue 取出的 job envelope）。"""
    run_id = job.get("run_id", "unknown")
    session_id = job.get("session_id", "")
    user_id = job.get("user_id", "")
    language = job.get("language", "zh-TW")

    logger.info(
        "[Worker] Starting job run_id=%s session=%s user=%s", run_id, session_id, user_id
    )

    # 同步 run 狀態到 Redis（讓 API 端知道在跑了）
    from core.shared_cache import set_json

    set_json(
        f"analysis:run:{run_id}",
        {
            "run_id": run_id,
            "session_id": session_id,
            "user_id": user_id,
            "status": "running",
            "content": "",
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
        },
        ttl=900,
    )

    # 發 run_started 事件
    from core.analysis_queue import publish_event

    publish_event(run_id, {"type": "run_started", "run_id": run_id})

    invoke_task: Optional[asyncio.Task] = None

    try:
        # ── 重建 manager（跟 API 端 bootstrap 完全一樣的參數）──────────────
        from core.agents.bootstrap import bootstrap
        from utils.user_client_factory import create_user_llm_client

        credentials = job["credentials"]
        user_client = create_user_llm_client(
            provider=credentials["provider"],
            api_key=credentials["api_key"],
            model=credentials["model"],
        )

        # bootstrap() 是同步函式（內部 PromptRegistry.load、skill 載入、MCP 載入等
        # sync I/O），且 MCP loader 內部 asyncio.run() 會因「已在 running loop」而失敗
        # （RuntimeError: asyncio.run() cannot be called from a running event loop）。
        # 走 run_sync bridge 丟到 thread executor——thread 內無 running loop，
        # asyncio.run() 才合法（對齊 api/routers/analysis.py:_do_bootstrap 的修法）。
        from api.utils import run_sync

        def _do_bootstrap():
            return bootstrap(
                llm_client=user_client,
                web_mode=job.get("web_mode", "web") == "web",
                language=language,
                user_tier=job.get("user_tier", "free"),
                user_id=user_id,
                session_id=session_id,
                key_fingerprint=job.get("key_fingerprint", ""),
                display_name=job.get("display_name"),
                wallet_address=job.get("wallet_address"),
            )

        manager = await run_sync(_do_bootstrap)

        # ── 設 progress_callback → 發事件到 Redis pub/sub ──────────────────
        loop = asyncio.get_running_loop()
        accumulated_content = {"value": ""}

        def _on_progress(event: Dict[str, Any]) -> None:
            """agent 的 progress callback → 發到 Redis。"""
            event_type = event.get("type", "")
            # token 事件要累積 content（讓 API 端 resync 時有完整快照）
            if event_type == "token":
                chunk = event.get("data", {}).get("chunk", "")
                if chunk:
                    accumulated_content["value"] += chunk

            publish_event(run_id, {"type": "progress", "data": event})

        def _on_progress_threadsafe(event: Dict[str, Any]) -> None:
            loop.call_soon_threadsafe(_on_progress, event)

        manager.progress_callback = _on_progress_threadsafe

        # ── 重建 graph_input（LangGraph Command）────────────────────────────
        from langgraph.types import Command

        graph_input_raw = job.get("graph_input", {})
        graph_input = Command(
            goto=graph_input_raw.get("goto", "claw_loop"),
            update=graph_input_raw.get("update", {}),
        )

        # resume 場景：帶 resume_answer
        resume_answer = job.get("resume_answer")
        if resume_answer is not None:
            graph_input = Command(resume=resume_answer)

        config = job.get("config", {})
        config.setdefault("configurable", {})
        config["configurable"].setdefault("thread_id", session_id)

        # ── 背景監聽撤銷 ────────────────────────────────────────────────────
        from core.analysis_queue import listen_for_control

        invoke_task = asyncio.create_task(
            asyncio.wait_for(
                manager.graph.ainvoke(graph_input, config),
                timeout=_ANALYSIS_TIMEOUT,
            )
        )

        control_task = asyncio.create_task(
            listen_for_control(run_id, lambda: invoke_task.cancel())
        )

        # ── 執行 ────────────────────────────────────────────────────────────
        result = await invoke_task
        control_task.cancel()

        # ── 處理結果 ────────────────────────────────────────────────────────
        interrupt_events = result.get("__interrupt__", []) if isinstance(result, dict) else []
        if interrupt_events:
            # HITL interrupt（consent gate 等）→ 發 hitl_question 事件
            iv = interrupt_events[0].value
            publish_event(run_id, {"type": "hitl_question", "data": iv})
            publish_event(run_id, {"done": True, "waiting": True})
            _update_run_status(run_id, "waiting")
            logger.info("[Worker] Job paused for HITL: run_id=%s", run_id)
            return

        response = result.get("final_response") if isinstance(result, dict) else None
        if not response:
            response = "（分析完成但無最終回覆）"

        # ── 存 DB ───────────────────────────────────────────────────────────
        from api.utils import run_sync
        from core.database.chat import save_chat_message

        response_metadata = result.get("response_metadata", {}) if isinstance(result, dict) else {}
        scam_ev = response_metadata.get("scam_evidence")

        await run_sync(
            lambda: save_chat_message(
                "assistant",
                response,
                session_id=session_id,
                user_id=user_id,
                metadata={"scam_evidence": scam_ev} if scam_ev else None,
            )
        )

        # ── 發 final + done 事件 ────────────────────────────────────────────
        publish_event(
            run_id,
            {"content": response, "type": "final"},
        )
        publish_event(
            run_id,
            {
                "type": "response_metadata",
                "data": response_metadata,
            },
        )
        publish_event(run_id, {"done": True})

        _update_run_status(run_id, "completed", content=response)
        logger.info(
            "[Worker] Job completed: run_id=%s response_len=%d",
            run_id,
            len(response),
        )

    except asyncio.CancelledError:
        logger.info("[Worker] Job cancelled (revoke): run_id=%s", run_id)
        publish_event(
            run_id,
            {
                "type": "revoked",
                "message": "授權已撤銷，Agent 已停止執行。",
                "done": True,
            },
        )
        _update_run_status(run_id, "revoked")
        raise

    except asyncio.TimeoutError:
        logger.error("[Worker] Job timed out: run_id=%s", run_id)
        publish_event(
            run_id,
            {
                "error": f"分析超時（超過 {_ANALYSIS_TIMEOUT} 秒）",
                "done": True,
            },
        )
        _update_run_status(run_id, "timeout", error="analysis_timeout")

    except Exception as exc:
        logger.error("[Worker] Job failed: run_id=%s\n%s", run_id, traceback.format_exc())
        publish_event(
            run_id,
            {"error": str(exc)[:200], "done": True},
        )
        _update_run_status(run_id, "error", error=str(exc)[:200])


def _update_run_status(
    run_id: str, status: str, *, content: str = "", error: Optional[str] = None
) -> None:
    """更新 run 狀態到 Redis shared_cache。"""
    from core.shared_cache import set_json

    set_json(
        f"analysis:run:{run_id}",
        {
            "run_id": run_id,
            "status": status,
            "content": content,
            "error": error,
            "finished_at": time.time(),
        },
        ttl=900,
    )


def _wait_for_dependencies(max_retries: int = 30, interval: int = 5) -> bool:
    """啟動時檢查核心依賴（Redis、DB、agent modules）。

    不直接 crash——失敗就等待重試，讓 Zeabur 有時間把 DB/Redis 起好。
    回傳 True = 依賴就緒，False = 放棄（max_retries 用完）。
    """
    for attempt in range(1, max_retries + 1):
        try:
            # 測試 Redis
            from core.analysis_queue import _get_sync_client

            client = _get_sync_client()
            if client is None:
                raise RuntimeError("Redis not available")
            client.ping()

            # 測試 DB
            from core.database.connection import get_connection

            conn = get_connection()
            conn.close()

            # 測試 agent imports
            from core.agents.bootstrap import bootstrap  # noqa: F401
            from utils.user_client_factory import create_user_llm_client  # noqa: F401

            logger.info(
                "[Worker] Dependencies ready (attempt %d/%d)", attempt, max_retries
            )
            return True

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            logger.warning(
                "[Worker] Dependencies not ready (attempt %d/%d): %s — retrying in %ds",
                attempt,
                max_retries,
                exc,
                interval,
            )
            import time as _time

            _time.sleep(interval)

    logger.error("[Worker] Dependencies failed after %d attempts — giving up", max_retries)
    return False


def main() -> None:
    """Worker 主循環：等待依賴 → BRPOP queue → asyncio.run(job) → 重複。

    設計：
    - 啟動時等待 Redis/DB 就緒（不 crash，符合「待機機制」要求）
    - BRPOP 是阻塞操作——閒置時不佔 CPU（符合「排隊不搶資源」要求）
    - job 失敗不 crash——log + 繼續等下一個 job
    """
    # Worker image（Dockerfile.analysis-worker）不含 mcp-servers 目錄——MCP server
    # 是主 Dockerfile build 時 git clone 的。即使 MCP_ENABLED 被專案級 env 設成 1，
    # worker image 裡沒那個檔案，載入必定失敗。這裡依「檔案實際存在與否」決定，
    # 而非盲從 env：檔案不存在就強制關，避免每個 job 都噴 WARNING。
    if os.getenv("MCP_ENABLED", "").lower() in ("1", "true", "yes"):
        mcp_path = None
        try:
            from core.tools.mcp_loader import _CRYPTO_TRADER_PATH as mcp_path
        except ImportError:
            pass
        if not mcp_path or not os.path.isfile(mcp_path):
            os.environ["MCP_ENABLED"] = "0"
            logger.info(
                "[Worker] MCP server 檔案不存在（worker image 無 mcp-servers），"
                "自動關閉 MCP。這是預期行為——worker 不需要 MCP。"
            )

    logger.info("[Worker] Analysis worker starting...")

    # 等待依賴就緒（不 crash）
    if not _wait_for_dependencies():
        # 依賴始終無法就緒——不 exit（避免 k8s BackOff），進入慢速重試
        logger.warning("[Worker] Entering slow retry mode (60s intervals)")
        while True:
            import time as _time

            _time.sleep(60)
            if _wait_for_dependencies(max_retries=1):
                break
        logger.info("[Worker] Dependencies recovered, entering main loop")

    from core.analysis_queue import dequeue_job

    logger.info(
        "[Worker] Ready. Waiting for jobs on 'analysis:queue' (idle, no CPU usage)..."
    )

    while True:
        try:
            # BRPOP 阻塞等待——閒置時不佔 CPU
            job = dequeue_job(timeout=30)
            if job is None:
                continue

            logger.info(
                "[Worker] Dequeued job: run_id=%s query=%s",
                job.get("run_id"),
                str(job.get("graph_input", {}).get("update", {}).get("query", ""))[:50],
            )

            asyncio.run(_run_job(job))

        except KeyboardInterrupt:
            logger.info("[Worker] Shutting down (keyboard interrupt)")
            break
        except SystemExit:
            raise
        except Exception as exc:
            logger.error("[Worker] Main loop error: %s — continuing", exc)
            # 不要掛掉——繼續等下一個 job
            import time as _time

            _time.sleep(2)


if __name__ == "__main__":
    main()
