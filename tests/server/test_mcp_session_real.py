"""Real stdio MCP servers against the real SDK (0.1.61 PR 4 review C1/C2/C3).

Only a real process shows how the SDK really fails; fakes cannot. The `real_mcp` marker lifts the
unit-test spawn guard and nothing else: these tests run on CI and on the Mac."""
import asyncio
import os
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
