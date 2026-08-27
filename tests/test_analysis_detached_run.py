"""客戶端斷線後，分析要繼續跑完並存檔，而不是被取消。

使用者回報：手機切到別的 App 再切回來就出現 network error，內容全沒了。
原因是 SSE generator 結束時 `invoke_task.cancel()` 把分析殺掉，而存檔是在
分析完成之後才做 —— 於是工作丟失、什麼都沒留下。

手機切換 App 必然斷線，取消等於每次切出去都白跑。改成交給背景收尾。
代價是任務脫離連線後沒人看著，所以閒置監控必須在伺服器端。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from api.routers import analysis

ANALYSIS_SOURCE = Path(analysis.__file__).read_text(encoding="utf-8")


class _FakeManager:
    def __init__(self):
        self.progress_callback = lambda event: None


@pytest.mark.asyncio
async def test_detached_run_saves_result_after_disconnect(monkeypatch):
    """斷線後分析跑完，結果要寫進 DB。"""
    saved = {}

    def fake_save(role, content, session_id=None, user_id=None, metadata=None):
        saved.update(
            {"role": role, "content": content, "session_id": session_id, "user_id": user_id}
        )

    monkeypatch.setattr(analysis, "save_chat_message", fake_save)

    async def slow_analysis():
        await asyncio.sleep(0.05)
        return {"final_response": "背景跑完的分析結果"}

    task = asyncio.create_task(slow_analysis())
    manager = _FakeManager()

    await analysis._finish_analysis_detached(
        task,
        {"at": asyncio.get_running_loop().time()},
        manager=manager,
        session_id="sess-detached",
        user_id="user-1",
        language="zh-TW",
    )

    assert saved["role"] == "assistant"
    assert saved["content"] == "背景跑完的分析結果"
    assert saved["session_id"] == "sess-detached"
    # 收尾後要把 callback 清掉，避免留在共用的 manager 上
    assert manager.progress_callback is None


@pytest.mark.asyncio
async def test_detached_run_is_cancelled_when_idle_too_long(monkeypatch):
    """閒置超過上限要中止，否則卡住的任務會一直燒 token。"""
    monkeypatch.setattr(analysis, "DETACHED_IDLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(analysis, "_DETACHED_IDLE_CHECK_INTERVAL_SECONDS", 0.01)

    saved = {}
    monkeypatch.setattr(
        analysis,
        "save_chat_message",
        lambda *a, **k: saved.setdefault("called", True),
    )

    async def stuck_analysis():
        await asyncio.sleep(30)
        return {"final_response": "never"}

    task = asyncio.create_task(stuck_analysis())
    # 時間戳停在很久以前 → 一開始就算閒置
    stale = {"at": 0.0}

    await analysis._finish_analysis_detached(
        task,
        stale,
        manager=_FakeManager(),
        session_id="sess-stuck",
        user_id="user-1",
        language="zh-TW",
    )

    assert task.cancelled() or task.done()
    assert "called" not in saved, "卡住被中止的分析不該存檔"


@pytest.mark.asyncio
async def test_detached_run_does_not_save_when_no_final_response(monkeypatch):
    """HITL 中斷沒有 final_response，不可寫進對話紀錄。"""
    saved = {}
    monkeypatch.setattr(
        analysis,
        "save_chat_message",
        lambda *a, **k: saved.setdefault("called", True),
    )

    async def interrupted():
        return {"__interrupt__": [object()]}

    await analysis._finish_analysis_detached(
        asyncio.create_task(interrupted()),
        {"at": asyncio.get_running_loop().time()},
        manager=_FakeManager(),
        session_id="sess-hitl",
        user_id="user-1",
        language="zh-TW",
    )

    assert "called" not in saved


def test_disconnect_path_detaches_instead_of_cancelling():
    """接線檢查：斷線分支必須交接給背景，不可再取消任務。

    上面的行為測試直接呼叫 _finish_analysis_detached，驗的是收尾協程本身；
    如果有人把 generator 的斷線分支改回 invoke_task.cancel()，那些測試仍會通過。
    這個測試守的就是那條接線。
    """
    generator = re.search(
        r"async def event_generator_v4\(\):(.*?)\n        return StreamingResponse",
        ANALYSIS_SOURCE,
        re.S,
    )
    assert generator, "找不到 event_generator_v4 —— 測試需要更新"

    # 抓整個 CancelledError 分支（到下一個 except 為止）。
    # 舊 regex 用 `(.*?)\n\s*raise` 會停在「revoked 分支」的第一個 raise——
    # 後來新增的撤銷授權分支（run["revoked"] 的 if/raise）破壞了它，
    # 導致抓到的片段不含 detach_analysis（程式碼本身是對的）。
    match = re.search(
        r"except asyncio\.CancelledError:\s*\n(.*?)(?=\n\s*except )",
        generator.group(1),
        re.S,
    )
    assert match, "找不到 generator 的斷線分支 —— 測試需要更新"

    branch = match.group(1)
    assert "detach_analysis" in branch, (
        "斷線分支沒有呼叫 detach_analysis：客戶端一斷線分析就會被丟掉"
    )
    assert "invoke_task.cancel()" not in branch, (
        "斷線分支又在取消任務了 —— 手機切換 App 就會讓分析白跑"
    )


def test_frontend_treats_connection_loss_as_background_run():
    """前端接線：連線中斷不可顯示成錯誤。

    伺服器端已經改成斷線不取消分析，如果前端還把 TypeError（Chrome 的
    「Failed to fetch」、Safari 的「Load failed」、部分 WebView 的
    「network error」）當成失敗顯示紅字，使用者仍會以為分析掛了。
    """
    source = (
        Path(__file__).resolve().parents[1] / "web" / "js" / "chat-analysis.js"
    ).read_text(encoding="utf-8")

    assert "function isConnectionLostError" in source, "缺少連線中斷的判斷"
    assert "isConnectionLostError(err)" in source, (
        "catch 分支沒有先判斷連線中斷 —— 斷線會被顯示成一般錯誤"
    )
    assert "watchForBackgroundResult" in source, (
        "斷線後沒有安排取回背景分析結果"
    )

    # 連線中斷分支必須排在通用錯誤分支之前，否則永遠走不到
    lost_at = source.index("isConnectionLostError(err)")
    generic_at = source.index("normalizeChatErrorMessage(\n                    err?.message")
    assert lost_at < generic_at, "連線中斷判斷排在通用錯誤之後，永遠不會生效"


def test_idle_timeout_is_server_side():
    """閒置保護必須在伺服器端，客戶端走了之後才還有人看著。"""
    assert "DETACHED_IDLE_TIMEOUT_SECONDS" in ANALYSIS_SOURCE
    assert re.search(
        r"idle_for\s*>\s*DETACHED_IDLE_TIMEOUT_SECONDS", ANALYSIS_SOURCE
    ), "找不到伺服器端的閒置判斷"
