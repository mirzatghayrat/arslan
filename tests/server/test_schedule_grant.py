"""Scheduling sits behind a session grant (user ruling 2026-08-20,裁决①).

Creating a task spends future money on the user's key, so it asks once — the
same shape as a workspace write, and for the same reason: the user is agreeing
to a capability, not to one filename. Reading and cancelling are NOT gated:
refusing to let someone see or undo what was created would be the worse
failure.
"""
import pytest

from server.orchestrator import tool_loop


async def _resolve():
    return [{"key": "schedule_task", "description": "s"},
            {"key": "list_my_tasks", "description": "l"},
            {"key": "cancel_task", "description": "c"}]


class _Stub:
    def __init__(self, log):
        self.log = log

    async def execute(self, args):
        self.log.append(args)
        return {"ok": True}


async def _dispatch(key, args, *, grant=None, log=None):
    trace, convo = [], []
    return await tool_loop._dispatch_tool(
        key, args, "{}", resolve_tools=_resolve, emit=lambda e: None,
        tool_timeout_s=5, tool_trace=trace, convo=convo,
        confirm_schedule=grant)


async def test_creating_without_a_grant_callback_is_refused(monkeypatch):
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, "schedule_task", _Stub(log))
    r = await _dispatch("schedule_task", {"name": "n", "when": "every: 3600"}, grant=None)
    assert r["ok"] is False and log == []


async def test_creating_when_declined_is_refused(monkeypatch):
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, "schedule_task", _Stub(log))

    async def deny(name, when):
        return False
    r = await _dispatch("schedule_task", {"name": "n", "when": "every: 3600"}, grant=deny)
    assert r["ok"] is False and "declined" in r["error"].lower() and log == []


async def test_creating_when_granted_runs_and_shows_the_card_the_real_schedule(monkeypatch):
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, "schedule_task", _Stub(log))
    asked = []

    async def allow(name, when):
        asked.append((name, when))
        return True
    r = await _dispatch("schedule_task",
                        {"name": "morning CI", "when": "cron: 0 9 * * *"}, grant=allow)
    assert r["ok"] is True and log
    assert asked == [("morning CI", "cron: 0 9 * * *")]


@pytest.mark.parametrize("key,args", [
    ("list_my_tasks", {}),
    ("cancel_task", {"task_id": 1}),
])
async def test_seeing_and_undoing_are_never_gated(monkeypatch, key, args):
    """A user must always be able to find and cancel what was created."""
    monkeypatch.setitem(tool_loop.EXECUTORS, key, _Stub([]))

    async def explode(name, when):
        raise AssertionError("listing/cancelling must not ask for permission")
    r = await _dispatch(key, args, grant=explode)
    assert r["ok"] is True


async def test_the_three_gates_stay_independent(monkeypatch):
    """A schedule grant approves neither a command nor a workspace write."""
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, "write_file", _Stub(log))

    async def allow_schedule(name, when):
        return True

    trace, convo = [], []
    r = await tool_loop._dispatch_tool(
        "write_file", {"path": "a.txt", "content": "x"}, "{}",
        resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5,
        tool_trace=trace, convo=convo,
        confirm_workspace_write=None, confirm_schedule=allow_schedule)
    assert r["ok"] is False and log == []
