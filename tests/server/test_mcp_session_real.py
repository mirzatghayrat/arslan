"""Real stdio MCP servers against the real SDK (0.1.61 PR 4 review C1/C2/C3).

Only a real process shows how the SDK really fails; fakes cannot. The `real_mcp` marker lifts the
unit-test spawn guard and nothing else: these tests run on CI and on the Mac."""
import asyncio
import os
import re
import sys
import time
from pathlib import Path

import pytest
from mcp import types
from mcp.shared.exceptions import McpError

from server.mcp import session as sess
from server.mcp import spawn_env

pytestmark = pytest.mark.real_mcp
SERVER = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


@pytest.fixture
async def mgr(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    manager = sess.MCPSessionManager()
    yield manager
    await manager.aclose_all()


def _server(mode, sid=1, **env):
    return {"id": sid, "transport": "stdio", "command": sys.executable,
            "args": [str(SERVER), mode], "env": env}


def _pid(text):
    """The child's pid from its first stderr line ("pid is N")."""
    found = re.search(r"pid is (\d+)", text)
    return int(found.group(1)) if found else None


async def _gone(pid, within=3.0):
    """True once no process has this pid (polled: the SDK reaps it while closing)."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.05)
    return False


async def test_a_good_server_starts_lists_and_calls(mgr):
    listed = await mgr.list_tools(_server("ok"))
    assert [t.name for t in listed.tools] == ["a"]
    assert listed.tools[0].annotations.readOnlyHint is True
    result = await mgr.call_tool(_server("ok"), "a", {})
    assert result.content[0].text == "called a"


async def test_a_slow_initialize_is_bounded_by_the_budget_not_a_read_timeout(mgr, monkeypatch):
    monkeypatch.setattr(sess, "LIST_TIMEOUT_S", 0.5)      # a session-wide 0.5 s would kill this (C1)
    server = _server("slow_init", SLOW_INIT_S="1.5")
    with pytest.raises(TimeoutError):                     # C2: TimeoutError, never an ExceptionGroup
        await mgr.get_session(server, budget_s=0.5)
    assert mgr.cached(1) is None
    await mgr.get_session(server, budget_s=10)
    assert mgr.cached(1) is not None


async def test_a_crash_keeps_its_cause_and_its_stderr(mgr):
    with pytest.raises(McpError) as caught:
        await mgr.get_session(_server("crash_with_stderr"), budget_s=10)
    assert caught.value.error.code == types.CONNECTION_CLOSED
    assert mgr.non_json_lines(1) == 0
    assert "Error: REA_TOKEN is not set" in mgr.stderr_tail(1, secrets=[])


async def test_a_program_that_prints_usage_is_seen_as_not_mcp(mgr):
    with pytest.raises(McpError) as caught:
        await mgr.get_session(_server("usage_exit"), budget_s=10)
    assert caught.value.error.code == types.CONNECTION_CLOSED
    assert mgr.non_json_lines(1) >= 1


async def test_one_stray_stdout_line_is_not_fatal(mgr):
    listed = await mgr.list_tools(_server("garbage_then_ok"))
    assert [t.name for t in listed.tools] == ["a"] and mgr.non_json_lines(1) == 1


async def test_a_hung_tools_list_times_out_and_drops(mgr, monkeypatch):
    monkeypatch.setattr(sess, "LIST_TIMEOUT_S", 0.5)
    with pytest.raises(sess.ListTimeout):
        await mgr.list_tools(_server("hang_list"))
    assert mgr.cached(1) is None


async def test_list_changed_reaches_the_callback_without_blocking_the_session(mgr, monkeypatch):
    monkeypatch.setattr(sess, "LIST_TIMEOUT_S", 2.0)
    seen = []
    mgr.on_tools_changed = seen.append
    server = _server("list_changed")
    first = await mgr.list_tools(server)
    second = await mgr.list_tools(server)     # times out if the handler blocked the receive loop
    assert [t.name for t in first.tools] == ["a"]
    assert [t.name for t in second.tools] == ["a", "b"]
    for _ in range(40):
        if seen:
            break
        await asyncio.sleep(0.05)
    assert seen == [1]


async def test_pages_follow_the_cursor(mgr):
    server = _server("paged")
    first = await mgr.list_tools(server)
    second = await mgr.list_tools(server, cursor=first.nextCursor)
    assert first.nextCursor == "p2" and [t.name for t in second.tools] == ["b"]
    assert second.nextCursor is None


async def test_stderr_lands_in_the_servers_folder_masked_and_per_run(mgr, tmp_path):
    server = _server("echo_env", FAKE_SECRET="s3cr3t-value-123")
    began = time.monotonic()
    await mgr.get_session(server, budget_s=10)
    assert sess.log_path(1) == tmp_path / "mcp" / "1" / "stderr.log"
    tail = mgr.stderr_tail(1, secrets=spawn_env.secret_forms(server), since=began)
    assert "token is ****" in tail and "s3cr3t" not in tail
    assert f"cwd is {os.path.realpath(tmp_path / 'mcp' / '1')}" in tail     # its own folder
    later = time.monotonic()
    assert mgr.stderr_tail(1, secrets=[], since=later) == ""     # nothing started since `later`
    await mgr.drop(1)
    await mgr.get_session(_server("ok"), budget_s=10)            # a new run under the same id
    assert "token is" not in mgr.stderr_tail(1, secrets=[])


async def test_a_server_that_dies_mid_call_is_dropped_and_reported(mgr):
    told = []
    mgr.on_dropped = lambda sid, exc: told.append((sid, sess.is_dropped_error(exc)))
    server = _server("ok")
    await mgr.list_tools(server)
    with pytest.raises(McpError) as caught:
        await mgr.call_tool(server, "die", {})
    assert caught.value.error.code == types.CONNECTION_CLOSED
    assert mgr.cached(1) is None and told == [(1, True)]


# ── fix round 1 (review I-1, I-3, I-5a) ─────────────────────────────────────────────────────


async def test_a_start_past_its_budget_leaves_no_process_behind(mgr):
    # Held like a caller holds it. Without the cleanup in _open_session the child outlives the
    # error: only the garbage collector's async-generator finalizer would reap it, ~2 s later
    # and only once nothing references the failed open (measured, fix round 1).
    with pytest.raises(TimeoutError) as caught:
        await mgr.get_session(_server("slow_init", SLOW_INIT_S="30"), budget_s=0.5)
    pid = _pid(mgr.stderr_tail(1, secrets=[]))
    assert pid is not None and await _gone(pid, within=0.5)     # gone when the error arrives
    assert caught.value is not None


async def test_a_call_pending_when_its_session_is_dropped_ends_at_once_and_spares_the_next(
        mgr, monkeypatch):
    monkeypatch.setattr(sess, "CALL_TIMEOUT_S", 5.0)     # unwoken, the call would end at 5 s
    told = []
    mgr.on_dropped = lambda sid, exc: told.append(sid)
    server = _server("ok", SLOW_CALL_S="30")
    await mgr.list_tools(server)
    began = time.monotonic()
    call = asyncio.create_task(mgr.call_tool(server, "slow", {}))
    await asyncio.sleep(0.3)
    await mgr.drop(1)                         # Reconnect, set_folders, a health probe's timeout
    fresh = await mgr.get_session(server, budget_s=10)
    with pytest.raises(McpError) as caught:
        await call
    assert caught.value.error.code == types.CONNECTION_CLOSED
    assert time.monotonic() - began < 2.0
    assert mgr.cached(1) is fresh and told == []      # the stale call neither drops nor reports


async def test_a_list_pending_when_its_session_is_dropped_ends_at_once(mgr, monkeypatch):
    monkeypatch.setattr(sess, "LIST_TIMEOUT_S", 5.0)     # unwoken, the page would end at 5 s
    server = _server("hang_list")
    began = time.monotonic()
    page = asyncio.create_task(mgr.list_tools(server))
    await asyncio.sleep(0.3)
    await mgr.drop(1)
    with pytest.raises(McpError) as caught:
        await page
    assert caught.value.error.code == types.CONNECTION_CLOSED
    assert time.monotonic() - began < 2.0 and mgr.cached(1) is None


async def test_one_death_with_seven_calls_pending_ends_them_all_and_restarts_once(
        mgr, monkeypatch):
    monkeypatch.setattr(sess, "CALL_TIMEOUT_S", 5.0)
    told = []
    mgr.on_dropped = lambda sid, exc: told.append((sid, sess.is_dropped_error(exc)))
    server = _server("ok", SLOW_CALL_S="30")
    await mgr.list_tools(server)
    calls = [asyncio.create_task(mgr.call_tool(server, "slow", {})) for _ in range(6)]
    await asyncio.sleep(0.3)
    began = time.monotonic()
    calls.append(asyncio.create_task(mgr.call_tool(server, "die", {})))
    results = await asyncio.gather(*calls, return_exceptions=True)
    assert time.monotonic() - began < 1.5
    assert [getattr(getattr(r, "error", None), "code", r) for r in results] == (
        [types.CONNECTION_CLOSED] * 7)
    assert told == [(1, True)]                                   # one death, one restart
    fresh = await mgr.get_session(server, budget_s=10)           # the supervisor's restart
    await asyncio.sleep(0.3)                                     # nothing stale left to kill it
    assert mgr.cached(1) is fresh
    assert (await mgr.call_tool(server, "a", {})).content[0].text == "called a"


async def test_forget_during_a_start_leaves_one_process_and_no_old_folder(mgr, tmp_path):
    server = _server("slow_init", SLOW_INIT_S="1")
    first = asyncio.create_task(mgr.get_session(server, budget_s=10))
    log = sess.log_path(1)
    for _ in range(150):                          # until the child is up and has said its pid
        if log.exists() and "pid is" in log.read_text():
            break
        await asyncio.sleep(0.02)
    first_pid = _pid(log.read_text())
    await mgr.forget(1)                           # deleted while it started
    second = asyncio.create_task(mgr.get_session(server, budget_s=10))   # its id handed out again
    with pytest.raises(sess.NotStarted):
        await first
    session = await second
    second_pid = _pid(mgr.stderr_tail(1, secrets=[]))
    assert first_pid is not None and second_pid not in (None, first_pid)
    assert await _gone(first_pid)                 # the overtaken start left nothing running
    os.kill(second_pid, 0)                        # and the one live process is the cached one
    assert mgr.cached(1) is session
    [moved] = (tmp_path / "mcp" / sess.FORGOTTEN_DIR).iterdir()
    assert f"pid is {first_pid}" in (moved / "stderr.log").read_text()
    assert f"pid is {first_pid}" not in log.read_text()
