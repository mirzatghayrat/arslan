"""The session manager with fakes (0.1.61 §B1). The real SDK: test_mcp_session_real.py."""
import asyncio
import time
from datetime import timedelta

import anyio
import pytest
from mcp import types
from mcp.shared.exceptions import McpError

from server.mcp import session as sess
from server.mcp import spawn_env


class _Stack:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


class _Session:
    def __init__(self, failure=None):
        self.failure = failure
        self.timeouts = []

    async def list_tools(self, params=None):
        return types.ListToolsResult(tools=[types.Tool(name="a", inputSchema={})])

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        self.timeouts.append(read_timeout_seconds)
        if self.failure is not None:
            raise self.failure
        return "ok"


def _server(sid=1, **kw):
    return {"id": sid, "transport": "stdio", "command": "x", "args": [], "env": {}, **kw}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    return tmp_path


async def test_one_server_opens_once_and_another_is_not_held_up(monkeypatch):
    mgr = sess.MCPSessionManager()
    opened = []

    async def fake_open(server):
        opened.append(server["id"])
        if server["id"] == 1:
            await asyncio.sleep(0.5)
        return _Session(), _Stack()
    monkeypatch.setattr(mgr, "_open_session", fake_open)
    slow = [asyncio.create_task(mgr.get_session(_server(1))) for _ in range(2)]
    await asyncio.sleep(0.05)
    began = time.monotonic()
    await mgr.get_session(_server(2))
    assert time.monotonic() - began < 0.3            # server 2 is not behind server 1's lock
    first, second = await asyncio.gather(*slow)
    assert first is second and opened.count(1) == 1


async def test_a_start_that_outlives_its_budget_times_out_and_caches_nothing(monkeypatch):
    mgr = sess.MCPSessionManager()

    async def slow_open(server):
        await asyncio.sleep(1)
        return _Session(), _Stack()
    monkeypatch.setattr(mgr, "_open_session", slow_open)
    with pytest.raises(TimeoutError):
        await mgr.get_session(_server(), budget_s=0.05)
    with pytest.raises(TimeoutError):
        await mgr.get_session(_server(start_budget_s=0.05))   # the budget travels in the server dict
    assert mgr.cached(1) is None


async def test_a_call_never_starts_a_process(monkeypatch):
    mgr = sess.MCPSessionManager()

    async def must_not_open(server):
        raise AssertionError("a tool call opened a session")
    monkeypatch.setattr(mgr, "_open_session", must_not_open)
    with pytest.raises(sess.NotStarted):
        await mgr.call_tool(_server(), "a", {})


async def test_a_call_has_120_s_and_a_server_error_answer_keeps_the_session():
    mgr = sess.MCPSessionManager()
    session = _Session(McpError(types.ErrorData(code=-32602, message="bad arguments")))
    mgr._sessions[1] = (session, _Stack())
    with pytest.raises(McpError):
        await mgr.call_tool(_server(), "a", {})
    assert session.timeouts == [timedelta(seconds=sess.CALL_TIMEOUT_S)]
    assert mgr.cached(1) is session


@pytest.mark.parametrize("failure, dropped", [
    (McpError(types.ErrorData(code=types.CONNECTION_CLOSED, message="Connection closed")), True),
    (anyio.ClosedResourceError(), True),
    (anyio.BrokenResourceError(), True),
    (McpError(types.ErrorData(code=408, message="Timed out")), False),
    (RuntimeError("schema"), False),
])
async def test_a_call_that_lost_its_session_drops_it_and_tells_the_supervisor(failure, dropped):
    mgr = sess.MCPSessionManager()
    stack = _Stack()
    mgr._sessions[1] = (_Session(failure), stack)
    told = []
    mgr.on_dropped = lambda sid, exc: told.append((sid, sess.is_dropped_error(exc)))
    with pytest.raises(type(failure)):
        await mgr.call_tool(_server(), "a", {})
    assert stack.closed and mgr.cached(1) is None and told == [(1, dropped)]


async def test_a_changed_command_under_the_same_id_reopens(monkeypatch):
    mgr = sess.MCPSessionManager()
    opened = []

    async def fake_open(server):
        opened.append(server["command"])
        return _Session(), _Stack()
    monkeypatch.setattr(mgr, "_open_session", fake_open)
    await mgr.get_session(_server(command="old"))
    await mgr.get_session(_server(command="old"))
    await mgr.get_session(_server(command="new"))
    assert opened == ["old", "new"]


async def test_the_message_handler_counts_stray_lines_and_only_schedules():
    mgr = sess.MCPSessionManager()
    seen = []
    mgr.on_tools_changed = seen.append
    handle = mgr._handler(7)
    await handle(ValueError("not JSON"))
    await handle(types.ServerNotification(types.ToolListChangedNotification()))
    await handle(types.ServerNotification(types.ResourceListChangedNotification()))
    assert mgr.non_json_lines(7) == 1 and seen == [7]


def test_the_tail_is_the_newest_run_masked_and_clean(data):
    log = sess.server_dir(3) / "stderr.log"
    old = "".join(f"old {i}\n" for i in range(5))
    new = "".join(f"line {i} key=s3cr3t-value\x1b[31m red\x1b[0m\r\n" for i in range(30))
    log.write_text(f"\n{sess.START_MARK}a ---\n{old}\n{sess.START_MARK}b ---\n{new}")
    mgr = sess.MCPSessionManager()
    tail = mgr.stderr_tail(3, secrets=["s3cr3t-value"]).splitlines()
    assert len(tail) == 20 and tail[0] == "line 10 key=**** red" and tail[-1] == "line 29 key=**** red"
    mgr._log_marks[3] = 10.0
    assert mgr.stderr_tail(3, secrets=[], since=11.0) == ""


def test_a_big_log_is_cut_to_its_last_64_kb(data):
    log = sess.server_dir(4) / "stderr.log"
    log.write_bytes(b"a" * (300 * 1024) + b"END")
    sess.cap_log(log)
    body = log.read_bytes()
    assert len(body) == sess.LOG_KEEP_BYTES and body.endswith(b"END")


class _FakeStdio:
    seen: list = []

    def __init__(self, params, errlog=None):
        _FakeStdio.seen.append((params, errlog))

    async def __aenter__(self):
        return ("r", "w")

    async def __aexit__(self, *a):
        return False


class _FakeClient:
    kwargs: list = []

    def __init__(self, read, write, **kwargs):
        _FakeClient.kwargs.append(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        return None


@pytest.fixture
def fake_sdk(monkeypatch, data):
    import mcp
    import mcp.client.stdio as stdio_mod

    from server.mcp import proxy_resolve
    _FakeStdio.seen.clear()
    _FakeClient.kwargs.clear()
    monkeypatch.setattr(stdio_mod, "stdio_client", _FakeStdio)
    monkeypatch.setattr(mcp, "ClientSession", _FakeClient)
    monkeypatch.setattr(spawn_env, "merged_path", lambda: "/usr/bin:/bin")
    monkeypatch.setattr(spawn_env, "resolve_command", lambda c: c)
    monkeypatch.setattr(proxy_resolve, "resolve_proxy", lambda env: ({}, "none"))
    return data


async def test_a_bare_npx_runs_on_the_pinned_node_in_its_own_folder_with_its_own_log(fake_sdk, monkeypatch):
    monkeypatch.setattr(spawn_env, "pinned_command", lambda c: ("/rt/node/bin/npx", "/rt/node/bin"))

    def must_not_resolve(c):
        raise AssertionError("resolved on PATH although pinned")
    monkeypatch.setattr(spawn_env, "resolve_command", must_not_resolve)
    mgr = sess.MCPSessionManager()
    _, stack = await mgr._open_session(_server(command="npx", args=["-y", "rea-agents", "--mcp"]))
    await stack.aclose()
    params, errlog = _FakeStdio.seen[-1]
    assert params.command == "/rt/node/bin/npx"
    assert params.env["PATH"] == "/rt/node/bin:/usr/bin:/bin"
    assert params.cwd == str(sess.server_dir(1))
    assert errlog.closed and sess.START_MARK in sess.log_path(1).read_text()
    assert set(_FakeClient.kwargs[-1]) == {"message_handler"}    # no session-wide read timeout (C1)


async def test_a_path_set_on_the_server_follows_the_pinned_runtime(fake_sdk, monkeypatch):
    monkeypatch.setattr(spawn_env, "pinned_command", lambda c: ("/rt/node/bin/npx", "/rt/node/bin"))
    _, stack = await sess.MCPSessionManager()._open_session(
        _server(command="npx", env={"PATH": "/custom/bin"}))
    await stack.aclose()
    assert _FakeStdio.seen[-1][0].env["PATH"] == "/rt/node/bin:/custom/bin"


async def test_an_installed_server_keeps_its_sandbox_folder(fake_sdk, tmp_path):
    root = tmp_path / "cap"
    _, stack = await sess.MCPSessionManager()._open_session(_server(
        command="/bin/echo", sandbox={"root": str(root), "folders": [], "network": False}))
    await stack.aclose()
    params = _FakeStdio.seen[-1][0]
    assert params.command == "/usr/bin/sandbox-exec" and params.cwd == str(root / "home")


async def test_cleanup_noise_never_replaces_the_cause(fake_sdk, monkeypatch):
    import mcp
    import mcp.client.stdio as stdio_mod

    class _NoisyStdio(_FakeStdio):
        async def __aexit__(self, *a):
            raise ExceptionGroup("cleanup", [anyio.BrokenResourceError()])

    class _TimingOut(_FakeClient):
        async def initialize(self):
            raise McpError(types.ErrorData(code=408, message="Timed out"))
    monkeypatch.setattr(stdio_mod, "stdio_client", _NoisyStdio)
    monkeypatch.setattr(mcp, "ClientSession", _TimingOut)
    with pytest.raises(McpError):
        await sess.MCPSessionManager()._open_session(_server())


async def test_the_proxy_lookup_runs_off_the_event_loop(fake_sdk, monkeypatch):
    from server.mcp import proxy_resolve

    def slow_proxy(env):
        time.sleep(1.0)
        return {}, "none"
    monkeypatch.setattr(proxy_resolve, "resolve_proxy", slow_proxy)
    gaps = []

    async def ticker():
        last = time.monotonic()
        for _ in range(15):
            await asyncio.sleep(0.05)
            now = time.monotonic()
            gaps.append(now - last)
            last = now
    tick = asyncio.create_task(ticker())
    # Let the ticker take its first timestamp now: `_open_session` reaches the proxy lookup before
    # its first suspension point, so a synchronous lookup would otherwise block before the ticker
    # ever ran and leave every gap small (the mutation survived without this).
    await asyncio.sleep(0)
    _, stack = await sess.MCPSessionManager()._open_session(_server())
    await stack.aclose()
    await tick
    assert max(gaps) < 0.3
