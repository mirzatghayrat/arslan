"""Every MCP entry point goes through the supervisor (0.1.61 §B1); the old UI's contracts hold."""
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from mcp import types
from mcp.shared.exceptions import McpError

from server import crypto, main
from server.db.models import MCPServer
from server.mcp import session
from server.mcp import supervisor as sm
from server.services import capability_list, mcp_service


async def _seed(maker, sid=1, **kw):
    fields = {"label": f"s{sid}", "command": "x", "args": [], "status": "registered",
              "state": "starting", "env": crypto.encrypt(json.dumps({})), **kw}
    async with maker() as db:
        db.add(MCPServer(id=sid, **fields))
        await db.commit()


def _listing(*names):
    return types.ListToolsResult(tools=[types.Tool(name=n, inputSchema={}) for n in names])


async def _closed():
    return None


class _Live:
    """A session that answers tools/list."""

    async def list_tools(self, params=None):
        return _listing("a")


@pytest.fixture
async def own_supervisor(monkeypatch, tmp_path):
    """A fresh Supervisor in place of the process singleton (the code under test reads
    `supervisor.supervisor` when it runs), stopped afterwards. Not running: no loop, no boot."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    fresh = sm.Supervisor()
    monkeypatch.setattr(sm, "supervisor", fresh)
    yield fresh
    await asyncio.wait_for(fresh.stop(), 10)        # a hang fails the test, never stalls the run
    await asyncio.wait_for(session.manager.aclose_all(), 10)


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    from server.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client


async def _background_done(supervisor):
    pending = [t for t in supervisor._bg if not t.done()]
    if pending:
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 10)


# ── the brief's tests ────────────────────────────────────────────────────────────────────

async def test_the_supervisor_starts_at_boot_unless_switched_off(monkeypatch, tmp_path):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))       # boot also prunes <data>/mcp/.forgotten
    calls = []

    async def reset():
        calls.append("reset")
    monkeypatch.setattr(sm.supervisor, "reset_for_boot", reset)
    monkeypatch.setattr(sm.supervisor, "start", lambda **kw: calls.append("start"))
    monkeypatch.setenv("ARSLAN_MCP_SUPERVISOR", "0")
    assert await main._start_mcp_supervisor() is False and calls == []
    monkeypatch.setenv("ARSLAN_MCP_SUPERVISOR", "1")
    assert await main._start_mcp_supervisor() is True and calls == ["reset", "start"]


async def test_connect_returns_the_tools_or_raises_with_the_classified_cause(execution_db, monkeypatch, tmp_path):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    await _seed(execution_db)

    async def ok(server, cursor=None):
        return _listing("read_file")
    monkeypatch.setattr(session.manager, "list_tools", ok)
    tools = await mcp_service.connect(1)
    assert [t["name"] for t in tools] == ["read_file"] and tools[0]["suggested_tier"] == "safe"
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert (row.state, row.status) == ("ready", "connected")

    async def missing(server, cursor=None):
        raise FileNotFoundError("x")
    monkeypatch.setattr(session.manager, "list_tools", missing)
    with pytest.raises(mcp_service.MCPStartFailed, match="command `x` not found"):
        await mcp_service.connect(1)


async def test_adding_a_server_schedules_its_start_once(execution_db, monkeypatch):
    scheduled = []
    monkeypatch.setattr(sm.supervisor, "schedule", lambda sid, **kw: scheduled.append(sid))
    first = await mcp_service.add_server("fs", "npx", ["-y", "x"], {})
    again = await mcp_service.add_server("fs", "npx", ["-y", "x"], {})
    assert first["id"] == again["id"] and scheduled == [first["id"]]
    assert first["state"] == "starting"


async def test_the_switch_stops_and_starts_the_server(execution_db, monkeypatch):
    await _seed(execution_db, state="ready", status="connected")
    stack = SimpleNamespace(closed=False)

    async def aclose():
        stack.closed = True
    stack.aclose = aclose
    monkeypatch.setitem(session.manager._sessions, 1, ("live", stack))
    await mcp_service.set_host_allowed(1, False)
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert row.host_allowed is False and row.state == "off"
    assert stack.closed and session.manager.cached(1) is None
    await mcp_service.set_host_allowed(1, True)
    async with execution_db() as db:
        assert (await db.get(MCPServer, 1)).state == "starting"


async def test_deleting_removes_the_row_before_it_forgets_the_server(execution_db, monkeypatch):
    """Carry (Task 5 re-review): the row goes first, then `forget` — `forget`'s guard covers only
    its own inside, so in the old order a supervisor tick between the two found the row still
    there and started the deleted server again."""
    await _seed(execution_db)
    seen = []

    async def forget(sid):
        async with execution_db() as db:
            seen.append((sid, await db.get(MCPServer, sid)))
    monkeypatch.setattr(sm.supervisor, "forget", forget)
    await mcp_service.delete_server(1)
    async with execution_db() as db:
        assert await db.get(MCPServer, 1) is None
    assert seen == [(1, None)]                     # forgotten once, and only after the row was gone


async def test_removing_a_capability_removes_its_server_row_before_forgetting_it(execution_db, monkeypatch, tmp_path):
    """The same carry on the other delete path: removing an installed capability."""
    from datetime import datetime

    from server.db.models import CapabilitySource
    from server.services import capability_install
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    await _seed(execution_db, 7, state="ready", status="connected")
    async with execution_db() as db:
        db.add(CapabilitySource(id="src7", kind="mcp", name="x", candidate_id="c", runtime="uv", needs={},
                                grants={}, state="installed", mcp_server_id=7, created_at=datetime.utcnow()))
        await db.commit()
    seen = []

    async def forget(sid):
        async with execution_db() as db:
            seen.append((sid, await db.get(MCPServer, sid)))
    monkeypatch.setattr(sm.supervisor, "forget", forget)
    await capability_install.remove("src7")
    assert seen == [(7, None)]


async def test_a_health_probe_that_times_out_schedules_a_fresh_start(execution_db, monkeypatch):
    await _seed(execution_db, state="ready")
    monkeypatch.setattr(mcp_service, "_HEALTH_PROBE_TIMEOUT", 0.05)

    async def wedged(server, cursor=None):
        await asyncio.sleep(5)
    monkeypatch.setattr(session.manager, "list_tools", wedged)
    scheduled = []
    monkeypatch.setattr(sm.supervisor, "schedule", lambda sid, **kw: scheduled.append((sid, kw)))
    out = await mcp_service.check_health(1)
    assert out["health_status"] == "failing" and scheduled == [(1, {"fresh": True})]


async def test_the_server_list_carries_the_state(execution_db):
    await _seed(execution_db, state="failed")
    (row,) = await mcp_service.list_servers()
    assert row["state"] == "failed" and {"next_retry_at", "last_ok_at", "state_at"} <= row.keys()


async def test_capability_rows_say_starting_without_connect_and_trust_the_pinned_runtime(execution_db, monkeypatch):
    from server.services import capability_runtime
    await _seed(execution_db, 1, transport="http", command="", url="https://example.test/mcp",
                state="starting", status="connecting")
    await _seed(execution_db, 2, command="npx", state="ready", status="connected", host_allowed=True)
    monkeypatch.setattr(capability_runtime, "available", lambda: True)

    def nowhere(c):
        raise FileNotFoundError(c)
    monkeypatch.setattr("server.mcp.spawn_env.resolve_command", nowhere)
    rows = {r["key"]: r for r in await capability_list._mcp_rows()}
    assert (rows["mcp:1"]["state"], rows["mcp:1"]["reason"], rows["mcp:1"]["fix"]) == \
        ("setup", "not_connected", None)
    assert rows["mcp:2"]["state"] == "on"      # npx is not on PATH, but Arslan runs it on its own Node


# ── the carries (carries.md "Task 6 (wiring)") ───────────────────────────────────────────

async def test_a_health_probe_that_waited_for_a_start_never_kills_it(execution_db, own_supervisor, monkeypatch):
    """Carry 2b: a probe that times out waiting for a start the supervisor runs (the session lock)
    skips the drop — the drop would overtake that start and cost a whole new one (cold budget
    120 s) — and answers with the server's state; nothing is written as failing."""
    await _seed(execution_db, state="ready", status="connected", health_status="ok")
    monkeypatch.setattr(mcp_service, "_HEALTH_PROBE_TIMEOUT", 0.05)
    opening, release, opens = asyncio.Event(), asyncio.Event(), []

    async def slow_open(server):
        opens.append(server["id"])
        opening.set()
        await release.wait()
        return _Live(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", slow_open)
    start = asyncio.create_task(own_supervisor.restart(1))          # a Connect: it holds the lock
    try:
        await asyncio.wait_for(opening.wait(), 5)
        out = await asyncio.wait_for(mcp_service.check_health(1), 5)
    finally:
        release.set()
    result = await asyncio.wait_for(start, 5)
    assert (out["state"], out["health_status"], out["tool_count"]) == ("starting", "ok", None)
    assert result.state == "ready" and opens == [1]                 # the start ran to its end, once
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert (row.state, row.health_status, row.last_error) == ("ready", "ok", None)
    assert session.manager.cached(1) is not None


async def test_a_health_probe_whose_own_open_was_overtaken_reports_the_state(execution_db, own_supervisor, monkeypatch):
    """Carry 2b, the other side: a start that begins while the probe opens drops first, so the
    probe's open ends NotStarted — overtaken, not failed: nothing is written, the state answers."""
    await _seed(execution_db, state="starting", status="connecting", health_status="ok")
    opening, release = asyncio.Event(), asyncio.Event()

    async def slow_open(server):
        opening.set()
        await release.wait()
        return _Live(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", slow_open)
    probe = asyncio.create_task(mcp_service.check_health(1))
    try:
        await asyncio.wait_for(opening.wait(), 5)
        await session.manager.drop(1)              # a start began: it drops before it opens
    finally:
        release.set()
    out = await asyncio.wait_for(probe, 5)
    assert (out["state"], out["health_status"], out["tool_count"]) == ("starting", "ok", None)
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert (row.health_status, row.last_error) == ("ok", None) and session.manager.cached(1) is None


async def test_a_probe_that_lost_the_session_it_ran_on_schedules_a_fresh_start(execution_db, monkeypatch):
    """Carry (Task 5 concern 3, 2c): list_tools drops the session it failed on and never tells the
    supervisor, so the probe does — a fresh start. A probe whose own open failed (no session
    before it) leaves the supervisor's plans alone."""
    await _seed(execution_db, state="ready", status="connected")

    class _Dead:
        async def list_tools(self, params=None):
            raise McpError(types.ErrorData(code=types.CONNECTION_CLOSED, message="Connection closed"))
    monkeypatch.delitem(session.manager._fingerprints, 1, raising=False)     # this session as it is
    monkeypatch.setitem(session.manager._sessions, 1, (_Dead(), SimpleNamespace(aclose=_closed)))
    scheduled = []
    monkeypatch.setattr(sm.supervisor, "schedule", lambda sid, **kw: scheduled.append((sid, kw)))
    out = await mcp_service.check_health(1)
    assert out["health_status"] == "failing" and session.manager.cached(1) is None
    assert scheduled == [(1, {"fresh": True})]

    async def no_such_command(server):
        raise FileNotFoundError("command 'x' was not found on PATH")
    monkeypatch.setattr(session.manager, "_open_session", no_such_command)
    out = await mcp_service.check_health(1)
    assert out["health_status"] == "failing" and scheduled == [(1, {"fresh": True})]   # no second


async def test_a_health_probe_failure_is_stored_with_the_servers_secrets_masked(execution_db, monkeypatch):
    """Every `last_error` writer masks (0.1.61 §B1), the probe's PB-2 line too: the column reaches
    the Capabilities page and, through a not-ready answer, a tool result."""
    secret = "-".join(["s3cr3t", "value", "456"])
    await _seed(execution_db, env=crypto.encrypt(json.dumps({"KEY": secret})))

    async def leaky(server, cursor=None):
        raise RuntimeError(f"rejected key {secret}")
    monkeypatch.setattr(session.manager, "list_tools", leaky)
    out = await mcp_service.check_health(1)
    async with execution_db() as db:
        stored = (await db.get(MCPServer, 1)).last_error
    assert out["health_status"] == "failing" and "health probe list_tools: rejected key ****" in stored
    assert secret not in stored and out["last_error"] == stored


async def test_an_edit_drops_the_old_session_and_schedules_a_fresh_start(execution_db, monkeypatch):
    """Carry (env-only edit): call_tool keeps using the cached session — it never compares
    fingerprints — so a change to a server's env, args or sandbox drops that session now and
    schedules a fresh start: the old env never answers another call, supervisor or not."""
    await _seed(execution_db, state="ready", status="connected",
                env=crypto.encrypt(json.dumps({"MODE": "a"})))
    closed = []

    async def aclose():
        closed.append(1)
    monkeypatch.setitem(session.manager._sessions, 1, ("live", SimpleNamespace(aclose=aclose)))
    scheduled = []
    monkeypatch.setattr(sm.supervisor, "schedule", lambda sid, **kw: scheduled.append((sid, kw)))
    async with execution_db() as db:
        (await db.get(MCPServer, 1)).env = crypto.encrypt(json.dumps({"MODE": "b"}))     # env only
        await db.commit()
    await mcp_service.restart_after_edit(1)
    assert closed == [1] and session.manager.cached(1) is None
    assert scheduled == [(1, {"fresh": True})]


async def test_a_failed_boot_reset_never_leaves_the_last_runs_ready_rows(execution_db, own_supervisor, monkeypatch):
    """Carry (boot): migration 0068 maps connected → ready, so a reset that fails must not leave
    those rows `ready` with their tools offered. The supervisor starts anyway, and the reset is
    retried in the background — for the rows nothing in this process has written since boot."""
    long_ago = sm._utcnow() - timedelta(days=1)
    await _seed(execution_db, 1, state="ready", status="connected")                # 0068's mapping
    await _seed(execution_db, 2, state="ready", status="connected", host_allowed=False, state_at=long_ago)
    await _seed(execution_db, 3, state="ready", status="connected",                # written after boot
                state_at=sm._utcnow() + timedelta(minutes=1))
    real_reset, calls = own_supervisor.reset_for_boot, []

    async def flaky(**kw):
        calls.append(kw)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return await real_reset(**kw)
    monkeypatch.setattr(own_supervisor, "reset_for_boot", flaky)
    monkeypatch.setattr(sm, "BOOT_RESET_RETRY_S", (0.0, 0.0))
    started = []
    monkeypatch.setattr(own_supervisor, "start", lambda **kw: started.append(kw))
    monkeypatch.setenv("ARSLAN_MCP_SUPERVISOR", "1")
    assert await main._start_mcp_supervisor() is True and started == [{}]
    await _background_done(own_supervisor)
    assert len(calls) == 2 and set(calls[1]) == {"written_before"}
    async with execution_db() as db:
        rows = {sid: await db.get(MCPServer, sid) for sid in (1, 2, 3)}
    assert (rows[1].state, rows[1].status) == ("starting", "connecting")
    assert rows[2].state == "off"
    assert rows[3].state == "ready"                # this process's own write stands


async def test_boot_sends_forgotten_folders_older_than_30_days_to_the_trash(own_supervisor, monkeypatch, tmp_path):
    """Carry (prune): a deleted server's folder waits under `<data>/mcp/.forgotten/<id>-<utc>/`;
    after 30 days boot moves it to the user's Trash with the existing helper — never deleted
    outright. An entry without a stamp is left alone, and a switched-off supervisor prunes nothing."""
    from server.services import capability_install
    forgotten = tmp_path / "mcp" / ".forgotten"
    now = sm._utcnow()

    def stamp(days):
        return (now - timedelta(days=days)).strftime("%Y%m%dT%H%M%S%fZ")
    old, old_n, recent, odd = (forgotten / f"1-{stamp(31)}", forgotten / f"2-{stamp(45)}-2",
                               forgotten / f"3-{stamp(29)}", forgotten / "notes")
    for folder in (old, old_n, recent, odd):
        folder.mkdir(parents=True)
        (folder / "stderr.log").write_text("x")
    trashed = []
    monkeypatch.setattr(capability_install, "to_trash", lambda path: trashed.append(path.name))

    async def reset():
        return None
    monkeypatch.setattr(own_supervisor, "reset_for_boot", reset)
    monkeypatch.setattr(own_supervisor, "start", lambda **kw: None)
    monkeypatch.setenv("ARSLAN_MCP_SUPERVISOR", "0")
    assert await main._start_mcp_supervisor() is False and trashed == []
    monkeypatch.setenv("ARSLAN_MCP_SUPERVISOR", "1")
    assert await main._start_mcp_supervisor() is True
    assert sorted(trashed) == sorted([old.name, old_n.name])


async def test_boot_skips_the_health_sweep_when_the_supervisor_runs_and_never_fails(monkeypatch):
    """Ruling 2: the opt-in PB-4 boot sweep runs only when the supervisor does not (it would probe
    every server while the supervisor starts them); neither ever breaks boot."""
    swept = []

    async def sweep():
        swept.append(1)
    monkeypatch.setattr(mcp_service, "check_health_all", sweep)
    monkeypatch.setenv("ARSLAN_MCP_HEALTH_ON_BOOT", "1")
    for supervised, expected in ((True, []), (False, [1])):
        swept.clear()

        async def start(supervised=supervised):
            return supervised
        monkeypatch.setattr(main, "_start_mcp_supervisor", start)
        await main._boot_mcp()
        assert swept == expected

    async def broken():
        raise RuntimeError("boom")
    monkeypatch.setattr(main, "_start_mcp_supervisor", broken)
    swept.clear()
    await main._boot_mcp()                         # never raises
    assert swept == [1]


async def test_a_failed_starts_last_error_is_only_the_supervisors_masked_text(execution_db, own_supervisor, monkeypatch):
    """Carry (Task 5 concern 5): discovery no longer writes `last_error`. A failed start leaves the
    supervisor's masked text — and nothing at all when the supervisor's own write was superseded
    (switched off meanwhile), where discovery's unmasked line used to stay behind."""
    secret = "-".join(["s3cr3t", "value", "123"])
    await _seed(execution_db, env=crypto.encrypt(json.dumps({"KEY": secret})))

    async def leaky(server, cursor=None):
        raise RuntimeError(f"upstream said: bad key {secret}")
    monkeypatch.setattr(session.manager, "list_tools", leaky)
    result = await asyncio.wait_for(own_supervisor.restart(1), 5)
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert row.last_error == result.last_error and "****" in row.last_error
    assert secret not in row.last_error

    async with execution_db() as db:
        (await db.get(MCPServer, 1)).last_error = None
        await db.commit()

    async def leaky_while_switched_off(server, cursor=None):
        own_supervisor._bump(1)                    # what set_enabled(off) does first
        raise RuntimeError(f"upstream said: bad key {secret}")
    monkeypatch.setattr(session.manager, "list_tools", leaky_while_switched_off)
    await asyncio.wait_for(own_supervisor.restart(1), 5)
    async with execution_db() as db:
        assert (await db.get(MCPServer, 1)).last_error is None


async def test_an_install_test_that_times_out_stops_the_start_it_began(execution_db, own_supervisor, monkeypatch):
    """Ruling 4: the install test is the one chat-reachable wait, bounded by TEST_TIMEOUT_S. When
    the bound ends it, the start it began does not run on in the background: its plan is
    cancelled and the server stays `off` — no orphan process."""
    from datetime import datetime

    from server.db.models import CapabilitySource
    from server.services import capability_flow
    await _seed(execution_db, 5, host_allowed=False, state="off")
    async with execution_db() as db:
        db.add(CapabilitySource(id="src5", kind="mcp", name="x", candidate_id="c", runtime="uv", needs={},
                                grants={}, state="installed", mcp_server_id=5, created_at=datetime.utcnow()))
        await db.commit()
    monkeypatch.setattr(capability_flow, "TEST_TIMEOUT_S", 0.2)
    cancelled = []

    async def never_answers(server):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(server["id"])
            raise
    monkeypatch.setattr(session.manager, "_open_session", never_answers)
    out = await asyncio.wait_for(capability_flow.test_mcp("src5"), 5)
    assert (out["ok"], out["stage"], out["detail"]) == (False, "start", "TimeoutError")
    assert cancelled == [5] and own_supervisor._inflight == {} and session.manager.cached(5) is None
    async with execution_db() as db:
        row = await db.get(MCPServer, 5)
    assert (row.state, row.host_allowed) == ("off", False)


async def test_a_connect_whose_start_was_overtaken_answers_with_the_next_start(execution_db, own_supervisor, monkeypatch):
    """Carry (Task 4 concern 4): an open overtaken by a drop (new folders while it started) is
    not a failure and must not surface as a generic 502: Connect starts it once more and answers
    with that start."""
    await _seed(execution_db)
    opens, first_open, release = [], asyncio.Event(), asyncio.Event()

    async def open_(server):
        opens.append(server["id"])
        if len(opens) == 1:
            first_open.set()
            await release.wait()
        return _Live(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", open_)
    connect = asyncio.create_task(mcp_service.connect(1))
    try:
        await asyncio.wait_for(first_open.wait(), 5)
        await session.manager.drop(1)              # e.g. set_folders while it started
    finally:
        release.set()
    tools = await asyncio.wait_for(connect, 5)
    assert [t["name"] for t in tools] == ["a"] and opens == [1, 1]


async def test_connect_answers_a_start_overtaken_twice_with_its_state_not_a_generic_502(
        api, execution_db, own_supervisor, monkeypatch):
    """The same carry at the API: overtaken again, Connect answers 503 with the state — it is
    starting — never a 502 that reads like a failure; a failed start stays a 502 with its cause;
    an unknown server is a 404, for Reconnect too."""
    await _seed(execution_db)
    real_restart, calls = own_supervisor.restart, []

    async def overtaken(server_id):
        calls.append(server_id)
        return sm.StartResult("starting")
    monkeypatch.setattr(own_supervisor, "restart", overtaken)
    r = await api.post("/api/v1/mcp/servers/1/connect")
    assert r.status_code == 503 and calls == [1, 1]
    assert r.json()["detail"].startswith("starting") and "starting by itself" in r.json()["detail"]

    async def failed(server_id):
        return sm.StartResult("parked", last_error="command `x` not found — install it, or give its full path")
    monkeypatch.setattr(own_supervisor, "restart", failed)
    r = await api.post("/api/v1/mcp/servers/1/connect")
    assert r.status_code == 502 and r.json()["detail"].startswith("command `x` not found")

    monkeypatch.setattr(own_supervisor, "restart", real_restart)    # unknown ids raise ValueError
    assert (await api.post("/api/v1/mcp/servers/999/connect")).status_code == 404
    assert (await api.post("/api/v1/mcp/servers/999/reconnect")).status_code == 404
