"""S1 (R7): a scheduled run is not offered background work (card S1).

A scheduled run met both conditions start_background_work had (a current task, not inside a job), so it
could start a job and, through it, put a card on the window (⓪Plan's proposal §6 item 6). Now it is
offered only when a card surface is bound (`permissions.current_asker()`), which a scheduled run never
binds. Its executor refuses too. Nothing tells a scheduled run to start background work: it cannot act on
this Mac at all (decide refuses unattended, U14 a).
"""
import sys

from server.orchestrator import arslan
from server.registry import hands_tools
from server.registry.task_tools import StartBackgroundWorkExecutor
from server.services import desktop_status, permissions, task_service
from server.services import personal_context as pc


async def _ask(frame):
    raise AssertionError("no card in this test")


async def _keys() -> set[str]:
    return {t["key"] for t in await arslan._arslan_tools()}


async def test_background_work_is_offered_only_where_someone_can_be_asked(execution_db, monkeypatch):
    monkeypatch.setattr(task_service, "current", lambda: object())
    with permissions.asking_with(_ask):
        assert "start_background_work" in await _keys()
    assert "start_background_work" not in await _keys()


async def test_its_executor_refuses_with_nobody_to_ask(execution_db, monkeypatch):
    started = []

    async def start(*a, **k):
        started.append(a)
        raise AssertionError("no job may start")
    from server.services import background_jobs
    monkeypatch.setattr(background_jobs, "start", start)
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="conv-1")):
        out = await StartBackgroundWorkExecutor().execute({"goal": "x", "criteria": [{"description": "y"}]})
    assert out == {"ok": False, "error_code": "background_unavailable"} and started == []


async def test_a_scheduled_run_is_not_told_to_start_background_work(execution_db, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: True)
    monkeypatch.setattr(task_service, "current", lambda: object())
    with desktop_status.working("conv-s", title="digest", kind="scheduled"):
        tools = await arslan._arslan_tools()
    text = " ".join(t["description"] for t in tools)
    assert "start background work" not in text and "start_background_work" not in {t["key"] for t in tools}
    assert "A scheduled run cannot act on this Mac" in text
