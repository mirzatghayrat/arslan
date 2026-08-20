"""The T1 write gate (spec 2026-08-20 P1 §1.5; user ruling 2: first-use grant,
then unconfirmed for the rest of the session).

Shape mirrors run_command's gate — a callback the WS layer injects — but the
UNIT is different: run_command confirms one command at a time, this confirms
the CATEGORY once ("may Arslan write in this workspace"). The session memory
therefore lives on the WS connection, not in this loop; here we only pin that
the loop asks, refuses safely without a callback, and never gates T0.
"""
import pytest

from server.orchestrator import tool_loop


async def _resolve():
    return [{"key": "write_file", "description": "write"},
            {"key": "edit_file", "description": "edit"},
            {"key": "read_file", "description": "read"}]


class _Stub:
    def __init__(self, log):
        self.log = log

    async def execute(self, args):
        self.log.append(args)
        return {"ok": True, "path": args.get("path")}


async def _dispatch(key, args, *, grant=None):
    trace, convo = [], []
    return await tool_loop._dispatch_tool(
        key, args, "{}", resolve_tools=_resolve, emit=lambda e: None,
        tool_timeout_s=5, tool_trace=trace, convo=convo,
        confirm_workspace_write=grant)


@pytest.mark.parametrize("key,args", [
    ("write_file", {"path": "a.txt", "content": "x"}),
    ("edit_file", {"path": "a.txt", "old": "a", "new": "b"}),
])
async def test_writers_refused_without_a_grant_callback(monkeypatch, key, args):
    """Safety default: no way to ask means no way to write."""
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, key, _Stub(log))
    r = await _dispatch(key, args, grant=None)
    assert r["ok"] is False
    assert "permission" in r["error"].lower() or "confirm" in r["error"].lower()
    assert log == []                       # the executor never ran


@pytest.mark.parametrize("key,args", [
    ("write_file", {"path": "a.txt", "content": "x"}),
    ("edit_file", {"path": "a.txt", "old": "a", "new": "b"}),
])
async def test_writers_refused_when_the_user_declines(monkeypatch, key, args):
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, key, _Stub(log))

    async def _deny(action, path):
        return False

    r = await _dispatch(key, args, grant=_deny)
    assert r["ok"] is False and "declined" in r["error"].lower()
    assert log == []


async def test_writer_runs_once_granted(monkeypatch):
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, "write_file", _Stub(log))
    asked = []

    async def _allow(action, path):
        asked.append((action, path))
        return True

    r = await _dispatch("write_file", {"path": "a.txt", "content": "x"}, grant=_allow)
    assert r["ok"] is True
    assert log == [{"path": "a.txt", "content": "x"}]
    assert asked == [("write_file", "a.txt")]     # the card gets the real action + path


async def test_readers_are_never_gated(monkeypatch):
    monkeypatch.setitem(tool_loop.EXECUTORS, "read_file", _Stub([]))

    async def _explode(action, path):
        raise AssertionError("T0 read tools must never ask for write permission")

    r = await _dispatch("read_file", {"path": "a.txt"}, grant=_explode)
    assert r["ok"] is True


async def test_run_command_gate_is_untouched(monkeypatch):
    """The two gates are independent: a write grant must not approve a command."""
    log = []
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", _Stub(log))

    async def _allow_write(action, path):
        return True

    trace, convo = [], []
    r = await tool_loop._dispatch_tool(
        "run_command", {"command": "git", "argv": ["status"]}, "{}",
        resolve_tools=_resolve, emit=lambda e: None, tool_timeout_s=5,
        tool_trace=trace, convo=convo,
        confirm_command=None, confirm_workspace_write=_allow_write)
    assert r["ok"] is False                 # still refused: no command callback
    assert log == []
