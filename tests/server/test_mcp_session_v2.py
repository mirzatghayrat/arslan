"""The session manager with fakes (0.1.61 §B1). The real SDK: test_mcp_session_real.py."""
import asyncio
import gc
import json
import logging
import time
from datetime import timedelta
from types import SimpleNamespace

import anyio
import pytest
from mcp import types
from mcp.shared.exceptions import McpError

from server import crypto
from server.db.models import MCPServer
from server.mcp import session as sess
from server.mcp import spawn_env
from server.mcp import supervisor as sm


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


@pytest.mark.parametrize("code", [-32602, types.INVALID_REQUEST])   # JSON-RPC's -32600, not 32600
async def test_a_call_has_120_s_and_a_server_error_answer_keeps_the_session(code):
    mgr = sess.MCPSessionManager()
    session = _Session(McpError(types.ErrorData(code=code, message="bad arguments")))
    mgr._sessions[1] = (session, _Stack())
    told = []
    mgr.on_dropped = lambda sid, exc: told.append(sid)
    with pytest.raises(McpError):
        await mgr.call_tool(_server(), "a", {})
    assert session.timeouts == [timedelta(seconds=sess.CALL_TIMEOUT_S)]
    assert mgr.cached(1) is session and told == []     # a server's answer restarts nothing


@pytest.mark.parametrize("failure, dropped", [
    (McpError(types.ErrorData(code=types.CONNECTION_CLOSED, message="Connection closed")), True),
    (McpError(types.ErrorData(code=sess.SESSION_TERMINATED, message="Session terminated")), True),
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


# ── LOAD2: a stdio program that exits at once, its pipe broken before EOF ─────────────────────

def _cancelled_with_cleanup(monkeypatch, cleanup: BaseException):
    """The shape the SDK gives (mcp 1.28.1): the stdio task group's writer fails, anyio cancels the
    task awaiting initialize (cancelling() is 0: nobody asked for it), and closing raises the group."""
    import mcp
    import mcp.client.stdio as stdio_mod

    class _Broken(_FakeStdio):
        async def __aexit__(self, *a):
            raise cleanup

    class _Cancelled(_FakeClient):
        async def initialize(self):
            raise asyncio.CancelledError()
    monkeypatch.setattr(stdio_mod, "stdio_client", _Broken)
    monkeypatch.setattr(mcp, "ClientSession", _Cancelled)


@pytest.mark.parametrize("cleanup", [
    ExceptionGroup("unhandled errors in a TaskGroup", [anyio.BrokenResourceError()]),
    ExceptionGroup("outer", [ExceptionGroup("inner", [anyio.BrokenResourceError()])]),
], ids=["group", "nested group"])
async def test_a_stdio_pipe_broken_before_eof_is_a_closed_connection(fake_sdk, monkeypatch, cleanup):
    _cancelled_with_cleanup(monkeypatch, cleanup)
    with pytest.raises(McpError) as caught:
        await sess.MCPSessionManager()._open_session(_server())
    assert caught.value.error.code == types.CONNECTION_CLOSED      # "not an MCP server", not "broken resource"


async def test_a_stdio_group_with_anything_else_in_it_is_still_the_cause(fake_sdk, monkeypatch):
    group = ExceptionGroup("tg", [anyio.BrokenResourceError(), RuntimeError("something else")])
    _cancelled_with_cleanup(monkeypatch, group)
    with pytest.raises(ExceptionGroup) as caught:
        await sess.MCPSessionManager()._open_session(_server())
    assert caught.value is group


async def test_http_keeps_the_group_as_the_cause(fake_sdk, monkeypatch):
    """The http rule is unchanged: a refused connection or an HTTP error fails a child task, and the
    group the close raises is what happened."""
    import mcp

    from server.mcp import oauth_flow
    group = ExceptionGroup("tg", [anyio.BrokenResourceError()])

    class _BrokenHttp:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return ("r", "w", lambda: None)

        async def __aexit__(self, *a):
            raise group

    class _Cancelled(_FakeClient):
        async def initialize(self):
            raise asyncio.CancelledError()

    async def no_tokens(server_id):
        return False
    monkeypatch.setattr(sess, "streamablehttp_client", _BrokenHttp)
    monkeypatch.setattr(mcp, "ClientSession", _Cancelled)
    monkeypatch.setattr(oauth_flow, "has_tokens", no_tokens)
    with pytest.raises(ExceptionGroup) as caught:
        await sess.MCPSessionManager()._open_session(_server(transport="http", url="https://mcp.example/x"))
    assert caught.value is group


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


# ── fix round 1 (review I-2 … I-5) ──────────────────────────────────────────────────────────


async def test_a_drop_during_a_start_is_not_undone(monkeypatch):
    mgr = sess.MCPSessionManager()
    opened = []

    async def slow_open(server):
        await asyncio.sleep(0.2)
        stack = _Stack()
        opened.append((server["sandbox"]["folders"], stack))
        return _Session(), stack
    monkeypatch.setattr(mgr, "_open_session", slow_open)
    old = _server(sandbox={"root": "/r", "folders": ["/old"], "network": False})
    new = _server(sandbox={"root": "/r", "folders": ["/old", "/new"], "network": False})
    start = asyncio.create_task(mgr.get_session(old))
    await asyncio.sleep(0.05)
    await mgr.drop(1)                       # set_folders: the grants changed while it started
    with pytest.raises(sess.NotStarted):
        await start
    assert opened[0][1].closed and mgr.cached(1) is None
    session = await mgr.get_session(new)
    assert [folders for folders, _ in opened] == [["/old"], ["/old", "/new"]]
    assert mgr.cached(1) is session


async def test_forget_during_a_start_keeps_the_lock_so_two_starts_never_overlap(data, monkeypatch):
    mgr = sess.MCPSessionManager()
    running, most = [0], [0]

    async def slow_open(server):
        running[0] += 1
        most[0] = max(most[0], running[0])
        await asyncio.sleep(0.2)
        running[0] -= 1
        return _Session(), _Stack()
    monkeypatch.setattr(mgr, "_open_session", slow_open)
    first = asyncio.create_task(mgr.get_session(_server()))
    await asyncio.sleep(0.05)
    await mgr.forget(1)
    second = asyncio.create_task(mgr.get_session(_server()))
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert isinstance(results[0], sess.NotStarted) and mgr.cached(1) is results[1]
    assert most[0] == 1


async def test_an_open_never_overwrites_a_cached_session(monkeypatch):
    mgr = sess.MCPSessionManager()
    theirs, mine = (_Session(), _Stack()), _Stack()

    async def open_while_another_caches(server):
        mgr._sessions[1] = theirs           # an opener that did not share this lock
        return _Session(), mine
    monkeypatch.setattr(mgr, "_open_session", open_while_another_caches)
    with pytest.raises(sess.NotStarted):
        await mgr.get_session(_server())
    assert mgr._sessions[1] is theirs and mine.closed and not theirs[1].closed


async def test_shutdown_during_a_start_caches_nothing(monkeypatch):
    mgr = sess.MCPSessionManager()
    stacks = []

    async def slow_open(server):
        await asyncio.sleep(0.2)
        stacks.append(_Stack())
        return _Session(), stacks[-1]
    monkeypatch.setattr(mgr, "_open_session", slow_open)
    start = asyncio.create_task(mgr.get_session(_server()))
    await asyncio.sleep(0.05)
    await mgr.aclose_all()
    with pytest.raises(sess.NotStarted):
        await start
    assert stacks[0].closed and mgr.cached(1) is None


async def test_a_changed_env_args_or_sandbox_under_the_same_id_reopens(monkeypatch):
    mgr = sess.MCPSessionManager()
    opened = []

    async def fake_open(server):
        opened.append(server)
        return _Session(), _Stack()
    monkeypatch.setattr(mgr, "_open_session", fake_open)
    base = _server(env={"TOKEN": "old"})
    env = {**base, "env": {"TOKEN": "new"}}
    args = {**env, "args": ["--verbose"]}
    grants = {**args, "sandbox": {"root": "/r", "folders": ["/a"], "network": False}}
    more = {**args, "sandbox": {"root": "/r", "folders": ["/a", "/b"], "network": False}}
    for server in (base, dict(base), env, args, grants, more, dict(more)):
        await mgr.get_session(server)
    assert opened == [base, env, args, grants, more]


async def test_forget_closes_clears_and_moves_the_folder_aside(data):
    mgr = sess.MCPSessionManager()
    (sess.server_dir(5) / "notes.txt").write_text("kept")
    sess.log_path(5).write_text(f"{sess.START_MARK}a ---\nthe deleted server's error\n")
    stack = _Stack()
    mgr._sessions[5] = (_Session(), stack)
    mgr._non_json[5], mgr._log_marks[5], mgr._proxy_sources[5] = 2, 1.0, "scutil"
    mgr._locks.get(5)
    await mgr.forget(5)
    assert stack.closed and mgr.cached(5) is None and 5 not in mgr._locks._locks
    assert (mgr.non_json_lines(5), mgr.proxy_source(5), 5 in mgr._log_marks) == (0, None, False)
    assert not (data / "mcp" / "5").exists() and mgr.stderr_tail(5, secrets=[]) == ""
    [moved] = (data / "mcp" / sess.FORGOTTEN_DIR).iterdir()
    assert moved.name.startswith("5-") and (moved / "notes.txt").read_text() == "kept"
    assert "the deleted server's error" in (moved / "stderr.log").read_text()   # never deleted
    sess.server_dir(6)
    mgr._sessions[6] = (_Session(), _Stack())
    await mgr.aclose_all()                  # a shutdown keeps every folder where it is
    assert (data / "mcp" / "6").is_dir()


async def test_the_stray_line_count_starts_over_with_each_run(monkeypatch):
    mgr = sess.MCPSessionManager()

    async def fake_open(server):
        return _Session(), _Stack()
    monkeypatch.setattr(mgr, "_open_session", fake_open)
    await mgr._handler(1)(ValueError("not JSON"))
    assert mgr.non_json_lines(1) == 1
    await mgr.get_session(_server())
    assert mgr.non_json_lines(1) == 0


def test_since_without_a_start_marker_is_never_an_earlier_runs_log(data):
    sess.server_dir(3)
    sess.log_path(3).write_text(f"{sess.START_MARK}a ---\nan earlier run's error\n")
    mgr = sess.MCPSessionManager()                # no start recorded in this process
    assert mgr.stderr_tail(3, secrets=[]) == "an earlier run's error"
    assert mgr.stderr_tail(3, secrets=[], since=0.0) == ""


async def test_a_failing_hook_never_replaces_the_cause_or_ends_the_session():
    mgr = sess.MCPSessionManager()

    def boom(*args):
        raise RuntimeError("boom")
    mgr.on_dropped = mgr.on_tools_changed = boom
    lost = McpError(types.ErrorData(code=types.CONNECTION_CLOSED, message="Connection closed"))
    mgr._sessions[1] = (_Session(lost), _Stack())
    with pytest.raises(McpError) as caught:
        await mgr.call_tool(_server(), "a", {})
    assert caught.value is lost
    await mgr._handler(1)(types.ServerNotification(types.ToolListChangedNotification()))


async def test_a_stale_failure_never_drops_the_session_that_replaced_it():
    mgr = sess.MCPSessionManager()
    newer = (_Session(), _Stack())

    class _Replaced(_Session):
        async def call_tool(self, name, arguments, read_timeout_seconds=None):
            mgr._sessions[1] = newer          # replaced while this call was in flight
            raise McpError(types.ErrorData(code=408, message="Timed out"))
    mgr._sessions[1] = (_Replaced(), _Stack())
    told = []
    mgr.on_dropped = lambda sid, exc: told.append(sid)
    with pytest.raises(McpError):
        await mgr.call_tool(_server(), "a", {})
    assert mgr._sessions[1] is newer and not newer[1].closed and told == []


async def test_a_failed_page_drops_only_the_session_it_ran_on():
    mgr = sess.MCPSessionManager()
    newer = (_Session(), _Stack())

    class _Replaced(_Session):
        async def list_tools(self, params=None):
            mgr._sessions[1] = newer
            raise anyio.BrokenResourceError()
    mgr._sessions[1] = (_Replaced(), _Stack())
    mgr._fingerprints[1] = sess._fingerprint(_server())
    with pytest.raises(anyio.BrokenResourceError):
        await mgr.list_tools(_server())
    assert mgr._sessions[1] is newer and not newer[1].closed


async def test_a_live_only_request_uses_the_live_session_and_never_restarts_it(monkeypatch):
    mgr = sess.MCPSessionManager()
    live = (_Session(), _Stack())
    mgr._sessions[1] = live
    mgr._fingerprints[1] = sess._fingerprint(_server())

    async def must_not_open(server):
        raise AssertionError("a live-only request opened a session")
    monkeypatch.setattr(mgr, "_open_session", must_not_open)
    page = await mgr.list_tools(_server(args=["--edited"], live_only=True))   # the row changed
    assert page.tools[0].name == "a" and mgr._sessions[1] is live and not live[1].closed


async def test_a_live_only_request_without_a_session_raises_at_once_and_opens_nothing(monkeypatch):
    mgr = sess.MCPSessionManager()
    release, opened = asyncio.Event(), []

    async def slow_open(server):
        opened.append(1)
        await release.wait()
        return _Session(), _Stack()
    monkeypatch.setattr(mgr, "_open_session", slow_open)
    with pytest.raises(sess.NotStarted):
        await mgr.list_tools(_server(live_only=True))
    assert opened == []
    start = asyncio.create_task(mgr.get_session(_server()))
    await asyncio.sleep(0.02)
    with pytest.raises(sess.NotStarted):         # a start in progress is not a live session
        await asyncio.wait_for(mgr.list_tools(_server(live_only=True)), 0.5)
    release.set()
    await start
    assert opened == [1]


async def test_a_live_only_request_naming_a_session_refuses_any_other(monkeypatch):
    mgr = sess.MCPSessionManager()
    old, new = _Session(), _Session()
    mgr._sessions[1] = (new, _Stack())              # the session the cursor came from was replaced

    async def must_not_open(server):
        raise AssertionError("a live-only request opened a session")
    monkeypatch.setattr(mgr, "_open_session", must_not_open)
    with pytest.raises(sess.NotStarted):
        await mgr.list_tools(_server(live_only=old))
    assert (await mgr.list_tools(_server(live_only=new))).tools[0].name == "a"


# ── final review, fix A (the real-process half is in test_mcp_session_real.py) ─────────────────


async def test_a_pending_call_fails_before_a_slow_close_ends(data):
    """`drop` wakes the requests pending on a session BEFORE its close runs — a close may take seconds
    (the SDK's 2 s grace, a terminate), and a call must not wait for it (carries: wake-before-close)."""
    mgr = sess.MCPSessionManager()
    entered = asyncio.Event()

    class _Pending:
        async def call_tool(self, name, args, read_timeout_seconds=None):
            entered.set()
            await asyncio.sleep(3600)

    async def slow_close():
        await asyncio.sleep(1.0)
    mgr._sessions[1] = (_Pending(), SimpleNamespace(aclose=slow_close))
    call = asyncio.create_task(mgr.call_tool({"id": 1}, "t", {}))
    await asyncio.wait_for(entered.wait(), 5)
    began = time.monotonic()
    dropping = asyncio.create_task(mgr.drop(1))
    with pytest.raises(McpError):
        await asyncio.wait_for(call, 5)
    assert time.monotonic() - began < 0.5            # woken at once, not after the 1 s close
    await asyncio.wait_for(dropping, 5)


class _Listed:
    async def list_tools(self, params=None):
        return types.ListToolsResult(tools=[types.Tool(name="a", inputSchema={})])


async def test_a_switch_off_during_an_overtaken_opens_close_returns(execution_db, data, monkeypatch):
    """An open overtaken by a drop closes what it opened (`_entry`), and that close is the plan's own
    await. A switch-off that cancels the plan in that close must not wait for the server to exit by
    itself. The fake close behaves as the SDK's does when cut (measured with real processes in
    test_mcp_session_real.py): a cancel in its 2 s grace leaves anyio's Process.aclose() waiting for
    the process with no bound."""
    monkeypatch.setattr(sess.manager, "_sessions", {})
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: "")
    async with execution_db() as db:
        db.add(MCPServer(id=1, label="s1", command="x", args=[], status="registered", state="starting",
                         env=crypto.encrypt(json.dumps({}))))
        await db.commit()
    opened, release, closing, process_gone = (asyncio.Event() for _ in range(4))

    async def cut_sensitive_close():
        closing.set()
        try:
            await asyncio.sleep(1.0)                 # the SDK's grace before it terminates
        except asyncio.CancelledError:
            await process_gone.wait()                # cut: Process.aclose() waits for the process
            raise
        process_gone.set()

    async def open_(server):
        opened.set()
        await release.wait()
        return _Listed(), SimpleNamespace(aclose=cut_sensitive_close)
    monkeypatch.setattr(sess.manager, "_open_session", open_)
    sup = sm.Supervisor()
    sup.start(run_loops=False)
    try:
        plan = sup._new_plan(1, "refresh")
        await asyncio.wait_for(opened.wait(), 5)
        await sess.manager.drop(1)                   # overtakes the open (an edit, a bound expiry …)
        release.set()
        await asyncio.wait_for(closing.wait(), 5)    # the open closes what it opened …
        await asyncio.wait_for(sup.set_enabled(1, False), 3)   # … and the switch-off cancels it there
        assert plan.done()
        await asyncio.wait_for(process_gone.wait(), 3)          # the close still ends the process
    finally:
        process_gone.set()
        await asyncio.wait_for(sup.stop(), 10)
        await asyncio.wait_for(sess.manager.aclose_all(), 10)


# ── final re-review: the closes `_close_uncut` holds (fix A) ───────────────────────────────────

async def test_a_close_that_ends_or_fails_is_let_go_of_and_a_failure_is_logged_not_raised(
        data, caplog):
    """Each close is held in `_closes` while it runs and let go of when it ends, normally or
    failing. A failure is logged with its cause; it is never raised at whoever dropped the session,
    and never left as a task exception nobody retrieves."""
    caplog.set_level(logging.DEBUG)
    mgr = sess.MCPSessionManager()

    async def ok_close():
        await asyncio.sleep(0.05)

    async def failing_close():
        await asyncio.sleep(0.05)
        raise RuntimeError("close blew up")
    mgr._sessions[1] = (object(), SimpleNamespace(aclose=ok_close))
    await mgr.drop(1)
    assert mgr._closes == set()
    mgr._sessions[2] = (object(), SimpleNamespace(aclose=failing_close))
    await mgr.drop(2)                                    # not raised at the caller
    assert mgr._closes == set()
    assert any("close failed" in r.getMessage() and "blew up" in r.getMessage()
               for r in caplog.records)
    gc.collect()
    assert not [r for r in caplog.records if "exception was never retrieved" in r.getMessage()]


async def test_a_close_left_running_by_a_cancelled_caller_is_held_and_waited_for_by_aclose_all(
        data):
    """A caller cancelled in the middle of a close leaves at once; the close goes on, held strongly
    in `_closes`; and `aclose_all` returns only once the closes it found have ended (the SDK's
    terminate step must run before the loop does)."""
    mgr = sess.MCPSessionManager()
    closing, release = asyncio.Event(), asyncio.Event()

    async def slow_close():
        closing.set()
        await release.wait()
    mgr._sessions[3] = (object(), SimpleNamespace(aclose=slow_close))
    dropping = asyncio.create_task(mgr.drop(3))
    await asyncio.wait_for(closing.wait(), 5)
    dropping.cancel()                                    # the caller is cut mid-close …
    await asyncio.gather(dropping, return_exceptions=True)
    assert len(mgr._closes) == 1                         # … the close is not: it runs on, held
    waiting = asyncio.create_task(mgr.aclose_all())
    await asyncio.sleep(0.05)
    assert not waiting.done()                            # aclose_all waits for it
    release.set()
    await asyncio.wait_for(waiting, 5)
    assert mgr._closes == set()


# ── a replaced start never caches a session (race b) ────────────────────────────────────────────

async def test_a_cancel_as_the_open_finishes_cancels_the_open_and_caches_nothing(data, monkeypatch):
    """A cancel delivered in the loop iteration in which the open finishes (where CPython 3.11's wait_for
    returned the session and lost the cancel, gh-86296) cancels the open itself: it closes its own stack, as
    _open_session does on any exception, and nothing is cached."""
    mgr = sess.MCPSessionManager()
    opening, gate, stack = asyncio.Event(), asyncio.Event(), _Stack()

    async def open_(server):
        try:
            opening.set()
            await gate.wait()
            return _Session(), stack
        except BaseException:
            await stack.aclose()
            raise
    monkeypatch.setattr(mgr, "_open_session", open_)
    start = asyncio.create_task(mgr.get_session(_server()))
    await asyncio.wait_for(opening.wait(), 5)
    gate.set()                                 # the open finishes in the next iteration …
    start.cancel()                             # … and the cancel is delivered in that same one
    with pytest.raises(asyncio.CancelledError):
        await start
    assert mgr.cached(1) is None and stack.closed


async def test_a_cancel_after_the_open_finished_closes_what_it_opened_and_caches_nothing(data, monkeypatch):
    """The open has returned its session, and the cancel lands before the start goes on: the session is
    closed (arslan.aio.within's dispose), nothing is cached, and the cancel goes on."""
    mgr = sess.MCPSessionManager()
    opening, gate, stack = asyncio.Event(), asyncio.Event(), _Stack()

    async def open_(server):
        opening.set()
        await gate.wait()
        return _Session(), stack
    monkeypatch.setattr(mgr, "_open_session", open_)
    start = asyncio.create_task(mgr.get_session(_server()))
    await asyncio.wait_for(opening.wait(), 5)
    gate.set()
    await asyncio.sleep(0)                     # the open runs and returns its session
    start.cancel()                             # before the start has taken it
    with pytest.raises(asyncio.CancelledError):
        await start
    assert mgr.cached(1) is None and stack.closed
