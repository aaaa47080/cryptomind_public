"""worker 模式串流修復的回歸測試（2026-08-25 回報：回答完成後進度卡持續轉圈）。

對應三個根因：
1. ``_stream_from_redis`` 把 token 事件原封以 ``{"type": "progress"}`` 幀轉發，
   前端 ``applyProgress`` 對 token 型別直接 return —— worker 模式下合成階段
   完全沒有串流文字，使用者只看到 "synthesizing" 卡轉圈。
   修復：與 in-process ``event_generator_v4`` 對齊，chunk 事件改發
   ``{"content": chunk, "type": "token"}`` 幀。
2. ``claw_loop`` 的 ``_on_tool_end`` 用「當前計數」當 step：並行 tool_calls
   （同一輪多個呼叫）時所有 finish 都打到最後一列，前面列的 spinner 永遠
   不會變 ✓。修復：``_ToolStepTracker`` 具名記帳，finish 用自己的 start step。
3. 合成階段的進度訊息是寫死的英文 "synthesizing"，未走 i18n。
"""

import json

import pytest

pytestmark = [pytest.mark.unit]


# ── 1. worker 模式 token 轉發 ────────────────────────────────────────────────


async def test_stream_from_redis_forwards_token_as_content_frame(monkeypatch):
    """token 事件（帶 chunk）必須以 content 幀轉發，讓前端串流顯示文字。"""
    import api.routers.analysis as analysis_mod
    import core.analysis_queue as queue_mod

    events = [
        {
            "type": "progress",
            "data": {
                "stage": "execute_task",
                "message": "正在查詢：即時加密貨幣價格",
                "type": "agent_start",
                "task_name": "即時加密貨幣價格",
                "step": 1,
                "success": True,
            },
        },
        {
            "type": "progress",
            "data": {
                "stage": "synthesize_response",
                "message": "synthesizing",
                "type": "token",
                "data": {"chunk": "比特幣目前"},
            },
        },
        {
            "type": "progress",
            "data": {
                "stage": "synthesize_response",
                "message": "synthesizing",
                "type": "token",
                "data": {"chunk": "約 6 萬美元"},
            },
        },
        {"type": "final", "content": "比特幣目前約 6 萬美元"},
        {"done": True},
    ]

    async def fake_subscribe(run_id, *, timeout=15.0):
        for ev in events:
            yield ev

    monkeypatch.setattr(queue_mod, "subscribe_events", fake_subscribe)

    run = {
        "run_id": "run-test-1",
        "session_id": "sess",
        "user_id": "u1",
        "status": "running",
        "content": "",
        "error": None,
        "started_at": 0.0,
        "finished_at": None,
        "next_event_id": 1,
        "events": [],
        "_last_sync": 0.0,
        "_subscribers": set(),
        "revoked": False,
    }

    frames = [f async for f in analysis_mod._stream_from_redis("run-test-1", run)]

    payloads = []
    for frame in frames:
        for line in frame.split("\n"):
            if line.startswith("data: "):
                payloads.append(json.loads(line[len("data: "):]))

    token_frames = [p for p in payloads if p.get("type") == "token" and p.get("content")]
    assert token_frames, "token 事件沒有以 content 幀轉發（worker 模式下使用者看不到串流文字）"
    assert token_frames[0]["content"] == "比特幣目前"

    # 帶 chunk 的 token 事件不應再以 progress 包裹重複轉發（會重複累積前端 fullContent）
    progress_wrapped_tokens = [
        p
        for p in payloads
        if p.get("type") == "progress" and (p.get("data") or {}).get("type") == "token"
    ]
    assert not progress_wrapped_tokens, "同一 chunk 同時以 progress 與 content 轉發會造成重複渲染"

    # 非 token progress（agent_start 等）仍照舊以 progress 幀轉發
    agent_progress = [
        p
        for p in payloads
        if p.get("type") == "progress" and (p.get("data") or {}).get("type") == "agent_start"
    ]
    assert agent_progress, "agent_start 進度事件不應被吃掉"

    # final + done 仍照舊
    assert any(p.get("type") == "final" for p in payloads)
    assert any(p.get("done") for p in payloads)


async def test_stream_from_redis_empty_token_stays_progress(monkeypatch):
    """空 chunk 的 token 事件（僅階段訊息）照舊走 progress 幀，不產生空 content 幀。"""
    import api.routers.analysis as analysis_mod
    import core.analysis_queue as queue_mod

    async def fake_subscribe(run_id, *, timeout=15.0):
        yield {
            "type": "progress",
            "data": {"stage": "synthesize_response", "message": "synthesizing", "type": "token", "data": {}},
        }
        yield {"done": True}

    monkeypatch.setattr(queue_mod, "subscribe_events", fake_subscribe)

    run = {
        "run_id": "run-test-2",
        "session_id": "sess",
        "user_id": "u1",
        "status": "running",
        "content": "",
        "error": None,
        "started_at": 0.0,
        "finished_at": None,
        "next_event_id": 1,
        "events": [],
        "_last_sync": 0.0,
        "_subscribers": set(),
        "revoked": False,
    }

    frames = [f async for f in analysis_mod._stream_from_redis("run-test-2", run)]
    payloads = [
        json.loads(line[len("data: "):])
        for frame in frames
        for line in frame.split("\n")
        if line.startswith("data: ")
    ]
    assert not [p for p in payloads if p.get("type") == "token"]
    assert [p for p in payloads if (p.get("data") or {}).get("message") == "synthesizing"]


# ── 2. 工具步驟記帳 ──────────────────────────────────────────────────────────


def test_tool_step_tracker_sequential():
    from core.agents.manager.claw_loop import _ToolStepTracker

    tracker = _ToolStepTracker()
    assert tracker.start("get_crypto_price") == 1
    assert tracker.end("get_crypto_price") == 1
    assert tracker.start("get_crypto_indicators") == 2
    assert tracker.end("get_crypto_indicators") == 2


def test_tool_step_tracker_parallel_calls_resolve_own_step():
    """並行 tool_calls：finish 必須指向自己的 start step，否則前端 spinner 卡死。"""
    from core.agents.manager.claw_loop import _ToolStepTracker

    tracker = _ToolStepTracker()
    assert tracker.start("get_crypto_price") == 1
    assert tracker.start("get_funding_rate") == 2
    # ToolMessage 依完成順序回流，第一個完成的是 step 1 的工具
    assert tracker.end("get_crypto_price") == 1
    assert tracker.end("get_funding_rate") == 2


def test_tool_step_tracker_unknown_name_falls_back_to_counter():
    from core.agents.manager.claw_loop import _ToolStepTracker

    tracker = _ToolStepTracker()
    tracker.start("get_crypto_price")
    # 防禦：查不到名字（異常路徑）退回當前計數，不丟例外
    assert tracker.end("never_started") == 1


# ── 3. synthesizing 訊息 i18n ────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["zh-TW", "zh-CN", "en", "ru"])
def test_synthesizing_progress_message_localized(lang):
    from core.i18n import t

    msg = t("ui_messages.progress.synthesizing", lang)
    assert msg and msg != "ui_messages.progress.synthesizing", (
        f"synthesizing 進度訊息缺少 {lang} 翻譯，前端會顯示英文原文"
    )
