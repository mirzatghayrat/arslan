import pytest
from server.orchestrator import tool_loop


async def _resolve():
    return [{"key": "run_command", "description": "shell"}]


@pytest.mark.asyncio
async def test_run_command_refused_without_confirm_cb(monkeypatch):
    calls = []

    class _Stub:
        async def execute(self, args):
            calls.append(args)
            return {"ok": True, "summary": "ran"}

    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", _Stub())
    trace, convo = [], []
    r = await tool_loop._dispatch_tool(
        "run_command", {"command": "git", "argv": ["status"]}, "{}",
        resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5,
        tool_trace=trace, convo=convo, confirm_command=None)
    assert r["ok"] is False
    assert "confirm" in r["error"].lower()
    assert calls == []


@pytest.mark.asyncio
async def test_run_command_declined_by_user(monkeypatch):
    class _Stub:
        async def execute(self, args):
            return {"ok": True, "summary": "ran"}
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", _Stub())

    async def _deny(cmd, argv):
        return False

    trace, convo = [], []
    r = await tool_loop._dispatch_tool(
        "run_command", {"command": "git", "argv": ["status"]}, "{}",
        resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5,
        tool_trace=trace, convo=convo, confirm_command=_deny)
    assert r["ok"] is False
    assert "declined" in r["error"].lower()


@pytest.mark.asyncio
async def test_run_command_approved_runs(monkeypatch):
    ran = []

    class _Stub:
        async def execute(self, args):
            ran.append(args)
            return {"ok": True, "summary": "ran"}
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", _Stub())

    async def _approve(cmd, argv):
        return True

    trace, convo = [], []
    r = await tool_loop._dispatch_tool(
        "run_command", {"command": "git", "argv": ["status"]}, "{}",
        resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5,
        tool_trace=trace, convo=convo, confirm_command=_approve)
    assert r["ok"] is True
    assert ran == [{"command": "git", "argv": ["status"]}]


@pytest.mark.asyncio
async def test_other_tools_unaffected_by_confirm_cb(monkeypatch):
    class _Stub:
        async def execute(self, args):
            return {"ok": True, "summary": "searched"}
    monkeypatch.setitem(tool_loop.EXECUTORS, "web_search", _Stub())

    async def _resolve_ws():
        return [{"key": "web_search", "description": "x"}]

    async def _deny(cmd, argv):
        raise AssertionError("confirm_command must not gate non-run_command tools")

    trace, convo = [], []
    r = await tool_loop._dispatch_tool(
        "web_search", {"query": "x"}, "{}", resolve_tools=_resolve_ws,
        emit=lambda e: None, tool_timeout_s=5, tool_trace=trace, convo=convo,
        confirm_command=_deny)
    assert r["ok"] is True
