"""Every MCP entry point goes through the supervisor (0.1.61 §B1); the old UI's contracts hold."""
import asyncio
import json
import logging
import threading
from datetime import timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from mcp import types
from mcp.shared.exceptions import McpError

from server import crypto, main
from server.db.models import MCPServer
from server.mcp import discovery, session
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


async def _boot_background_done():
    """Boot's own background work (the `.forgotten` prune, F5), awaited."""
    pending = [t for t in list(getattr(main, "_background", ())) if not t.done()]
    if pending:
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 10)


@pytest.fixture(autouse=True)
async def _boot_background_drained():
    """No test leaves boot's background work running behind it."""
    yield
    await _boot_background_done()


async def _until(predicate, *, tries=500):
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never met")


def _live_session(monkeypatch, sid, live=None, aclose=_closed):
    """`sid`'s live session, cached as the manager caches one (no fingerprint: used as it is)."""
    monkeypatch.delitem(session.manager._fingerprints, sid, raising=False)
    monkeypatch.setitem(session.manager._sessions, sid,
                        (live if live is not None else _Live(), SimpleNamespace(aclose=aclose)))


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
    monkeypatch.setattr(sm.supervisor, "schedule", lambda sid, **kw: scheduled.append((sid, kw)))
    first = await mcp_service.add_server("fs", "npx", ["-y", "x"], {})
    again = await mcp_service.add_server("fs", "npx", ["-y", "x"], {})
    # the first plan (spec §B1: up to 3 more attempts 1/2/4 s apart), never a one-attempt refresh
    assert first["id"] == again["id"] and scheduled == [(first["id"], {})]
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
    """A ready server's live session that does not answer within the bound is dropped (it must not
    poison later calls) and the supervisor restarts the server (fix round 1: the probe reports on
    the live session only)."""
    await _seed(execution_db, state="ready", status="connected")
    _live_session(monkeypatch, 1)
    monkeypatch.setattr(mcp_service, "_HEALTH_PROBE_TIMEOUT", 0.05)

    async def wedged(server, cursor=None):
        await asyncio.sleep(5)
    monkeypatch.setattr(session.manager, "list_tools", wedged)
    scheduled = []
    monkeypatch.setattr(sm.supervisor, "schedule", lambda sid, **kw: scheduled.append((sid, kw)))
    out = await mcp_service.check_health(1)
    assert out["health_status"] == "failing" and scheduled == [(1, {"fresh": True})]
    assert session.manager.cached(1) is None


async def test_the_server_list_carries_the_state(execution_db):
    await _seed(execution_db, state="failed")
    (row,) = await mcp_service.list_servers()
    assert row["state"] == "failed"
    assert {"next_retry_at", "last_ok_at", "state_at", "fail_count"} <= row.keys()


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

async def test_a_probe_during_a_start_answers_at_once_and_never_touches_its_session(
        execution_db, own_supervisor, monkeypatch):
    """Carry 2b by construction, F1/F2 (review P1b): a probe never waits for a start (no session
    lock) and never lists through the session a start is opening, so it can neither kill that start
    nor miss that session's death — it answers with the state at once; the start ends `ready`
    with its session, listed once."""
    await _seed(execution_db, state="ready", status="connected", health_status="ok")
    opening, release, opens, calls = asyncio.Event(), asyncio.Event(), [], []

    class _DiesOnSecondList:
        async def list_tools(self, params=None):
            calls.append(1)
            if len(calls) == 1:
                return _listing("a")
            raise McpError(types.ErrorData(code=types.CONNECTION_CLOSED, message="Connection closed"))

    async def slow_open(server):
        opens.append(server["id"])
        opening.set()
        await release.wait()
        return _DiesOnSecondList(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", slow_open)
    start = asyncio.create_task(own_supervisor.restart(1))          # a Connect: it holds the lock
    try:
        await asyncio.wait_for(opening.wait(), 5)
        out = await asyncio.wait_for(mcp_service.check_health(1), 5)     # at once: nothing to wait on
    finally:
        release.set()
    result = await asyncio.wait_for(start, 5)
    assert (out["state"], out["health_status"], out["tool_count"]) == ("starting", "ok", None)
    assert result.state == "ready" and opens == [1] and calls == [1]
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert (row.state, row.health_status, row.last_error) == ("ready", "ok", None)
    assert session.manager.cached(1) is not None


async def test_a_probe_never_spawns_and_switching_on_afterwards_starts_it(execution_db, own_supervisor, monkeypatch):
    """F2 (review P2): with no live session the probe answers with the stored state — it spawns
    nothing, so a switched-off server stays without a process, and switching it on afterwards
    starts it (the probe's own session used to make that switch a no-op: stuck `off`)."""
    await _seed(execution_db, state="off", status="connected", host_allowed=False)
    opens = []

    async def open_(server):
        opens.append(server["id"])
        return _Live(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", open_)
    out = await mcp_service.check_health(1)
    assert (out["state"], out["tool_count"]) == ("off", None) and opens == []
    assert session.manager.cached(1) is None
    own_supervisor.start(run_loops=False)
    await mcp_service.set_host_allowed(1, True)                 # the user's switch: on
    plans = [t for t in own_supervisor._inflight.values() if not t.done()]
    await asyncio.wait_for(asyncio.gather(*plans), 5)
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert (row.host_allowed, row.state) == (True, "ready") and opens == [1]


async def test_a_probe_that_lost_the_session_it_ran_on_schedules_a_fresh_start(execution_db, monkeypatch):
    """Carry (Task 5 concern 3, 2c): list_tools drops the session it failed on and never tells the
    supervisor, so the probe does — a fresh start. With no live session the probe opens nothing and
    schedules nothing: it answers with the stored state (fix round 1)."""
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

    opens = []

    async def no_such_command(server):
        opens.append(server["id"])
        raise FileNotFoundError("command 'x' was not found on PATH")
    monkeypatch.setattr(session.manager, "_open_session", no_such_command)
    out = await mcp_service.check_health(1)
    assert (out["state"], out["health_status"]) == ("ready", "failing")      # what is stored
    assert opens == [] and scheduled == [(1, {"fresh": True})]               # no open, no second


async def test_a_health_probe_failure_is_stored_with_the_servers_secrets_masked(execution_db, monkeypatch):
    """Every writer of `last_error` masks (0.1.61 §B1) — the supervisor, this probe and the executor
    (fix round 1, F3): the column reaches the Capabilities page, the server list and, through a
    not-ready answer, a tool result."""
    secret = "-".join(["s3cr3t", "value", "456"])
    await _seed(execution_db, state="ready", status="connected", env=crypto.encrypt(json.dumps({"KEY": secret})))
    _live_session(monkeypatch, 1)

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
    await _boot_background_done()                  # F5: the prune runs behind boot
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


# ── fix round 1 (task-6-fix-round-1.md, F1–F5) ───────────────────────────────────────────

async def test_a_start_whose_session_died_under_another_lister_never_ends_ready(execution_db, own_supervisor, monkeypatch):
    """F1 (review P1, a missed death): the session a start has just listed on dies under another
    caller's tools/list, which drops it, before the start has written its tools — the start must
    not then end `ready` with no session behind it (ruling 11): it ends `failed`, retry pending."""
    await _seed(execution_db)
    listed, write_gate, calls = asyncio.Event(), asyncio.Event(), []

    class _DiesOnSecondList:
        async def list_tools(self, params=None):
            calls.append(1)
            if len(calls) == 1:
                return _listing("a")
            raise McpError(types.ErrorData(code=types.CONNECTION_CLOSED, message="Connection closed"))

    async def open_(server):
        return _DiesOnSecondList(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", open_)
    real_write = discovery._write

    async def gated_write(server_id, tools, *, complete):
        listed.set()
        await write_gate.wait()
        return await real_write(server_id, tools, complete=complete)
    monkeypatch.setattr(discovery, "_write", gated_write)
    start = asyncio.create_task(own_supervisor.restart(1))
    try:
        await asyncio.wait_for(listed.wait(), 5)
        with pytest.raises(McpError):             # another caller lists on the live session: dead
            await session.manager.list_tools({"id": 1, "live_only": True})
        assert session.manager.cached(1) is None
    finally:
        write_gate.set()
    result = await asyncio.wait_for(start, 5)
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert result.state == "failed" and (row.state, row.status) == ("failed", "error")
    assert row.last_error.startswith("the server exited during start") and row.next_retry_at is not None


async def test_a_give_up_drop_waking_a_probe_is_not_a_death(execution_db, own_supervisor, monkeypatch):
    """F1 (review P11): a supervisor verb's deliberate drop — the give-up after 5 reconnects,
    "Arslan retries it later" — wakes a pending probe. That is not a death: the generation moved,
    so the probe schedules nothing, and the give-up's `failed` and its backoff land; nothing opens."""
    await _seed(execution_db, state="ready", status="connected")
    pending = asyncio.Event()

    class _Blocking:
        async def list_tools(self, params=None):
            pending.set()
            await asyncio.Event().wait()
    _live_session(monkeypatch, 1, _Blocking())
    monkeypatch.setattr(mcp_service, "_HEALTH_PROBE_TIMEOUT", 5.0)
    opens = []

    async def open_(server):
        opens.append(server["id"])
        return _Live(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", open_)
    own_supervisor.running = True                     # schedule() acts; no loop, no boot
    try:
        probe = asyncio.create_task(mcp_service.check_health(1))
        await asyncio.wait_for(pending.wait(), 5)
        await own_supervisor._give_up(1)
        await asyncio.wait_for(probe, 5)
        plans = [t for t in own_supervisor._inflight.values() if not t.done()]
        await asyncio.wait_for(asyncio.gather(*plans), 5)
    finally:
        own_supervisor.running = False
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert opens == [] and row.state == "failed" and row.next_retry_at is not None
    assert row.last_error.startswith("the server keeps dropping its connection")


async def test_a_probe_woken_by_a_deliberate_drop_writes_nothing(execution_db, own_supervisor, monkeypatch):
    """F1: a new plan's deliberate drop (its generation moved) wakes the probe pending on the old
    session. That is not the server failing: the probe writes nothing over the state the new plan
    owns, and schedules nothing."""
    await _seed(execution_db, state="ready", status="connected", health_status="ok")
    pending = asyncio.Event()

    class _Blocking:
        async def list_tools(self, params=None):
            pending.set()
            await asyncio.Event().wait()
    _live_session(monkeypatch, 1, _Blocking())
    monkeypatch.setattr(mcp_service, "_HEALTH_PROBE_TIMEOUT", 5.0)
    scheduled = []
    monkeypatch.setattr(own_supervisor, "schedule", lambda sid, **kw: scheduled.append((sid, kw)))
    probe = asyncio.create_task(mcp_service.check_health(1))
    await asyncio.wait_for(pending.wait(), 5)
    own_supervisor._bump(1)                    # a new plan began (it has written nothing yet) ...
    await session.manager.drop(1)              # ... and dropped the old session first
    out = await asyncio.wait_for(probe, 5)
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert (row.state, row.health_status, row.last_error) == ("ready", "ok", None)
    assert scheduled == [] and (out["state"], out["health_status"]) == ("ready", "ok")


async def test_a_probe_writes_nothing_once_the_state_left_ready(execution_db, own_supervisor, monkeypatch):
    """F2: the probe writes health and last_error only over a `ready` row. When the state moved on
    while it listed without any new plan or verb (a boot reset makes every enabled server
    `starting`), its finding is not written over the new state."""
    await _seed(execution_db, state="ready", status="connected", health_status="ok")
    pending = asyncio.Event()

    class _Blocking:
        async def list_tools(self, params=None):
            pending.set()
            await asyncio.Event().wait()
    _live_session(monkeypatch, 1, _Blocking())
    monkeypatch.setattr(mcp_service, "_HEALTH_PROBE_TIMEOUT", 5.0)
    monkeypatch.setattr(own_supervisor, "schedule", lambda sid, **kw: None)
    probe = asyncio.create_task(mcp_service.check_health(1))
    await asyncio.wait_for(pending.wait(), 5)
    await own_supervisor.reset_for_boot()      # `starting` — no generation moves
    await session.manager.drop(1)              # then the session dies under the probe
    out = await asyncio.wait_for(probe, 5)
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert (row.state, row.health_status, row.last_error) == ("starting", "ok", None)
    assert out["state"] == "starting"


async def test_a_probe_never_touches_a_starting_servers_session(execution_db, monkeypatch):
    """F2 / carry 2b: a server that is `starting` — even with the session its start has opened
    cached already — is answered with its state; the probe never lists through a start's session."""
    await _seed(execution_db, state="starting", status="connecting")
    calls = []

    class _Recording:
        async def list_tools(self, params=None):
            calls.append(1)
            return _listing("a")
    _live_session(monkeypatch, 1, _Recording())
    out = await asyncio.wait_for(mcp_service.check_health(1), 5)
    assert out["state"] == "starting" and calls == []


async def test_a_probe_never_touches_a_server_whose_start_is_queued(execution_db, own_supervisor, monkeypatch):
    """F2 / carry 2b: a start queued for a slot (in flight, but it has neither dropped the session
    nor written yet) owns the server — the probe answers with the state and never lists."""
    await _seed(execution_db, state="ready", status="connected")
    calls = []

    class _Recording:
        async def list_tools(self, params=None):
            calls.append(1)
            return _listing("a")
    _live_session(monkeypatch, 1, _Recording())

    async def open_(server):
        return _Live(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", open_)
    own_supervisor.start(run_loops=False)
    for _ in range(sm.MAX_CONCURRENT):
        await own_supervisor._sem.acquire()       # every slot busy: the start waits its turn
    try:
        own_supervisor.schedule(1, fresh=True)
        await _until(lambda: own_supervisor.start_in_flight(1))
        out = await asyncio.wait_for(mcp_service.check_health(1), 5)
        assert out["state"] == "ready" and calls == []
    finally:
        for _ in range(sm.MAX_CONCURRENT):
            own_supervisor._sem.release()
    plans = [t for t in own_supervisor._inflight.values() if not t.done()]
    await asyncio.wait_for(asyncio.gather(*plans), 5)
    async with execution_db() as db:
        assert (await db.get(MCPServer, 1)).state == "ready"


async def test_a_probe_of_a_failed_server_keeps_the_classified_cause(execution_db, monkeypatch):
    """F2 (review P3): a probe never touches a server that is not `ready` — whatever its listing
    would say, the supervisor's classified cause, state and retry stay, so the prompt keeps its
    reason."""
    cause = "did not start within 120 s (still downloading?)"
    await _seed(execution_db, state="failed", status="error", last_error=cause, fail_count=1)
    for behaviour in ("ok", "boom"):
        async def probe_list(server, cursor=None, behaviour=behaviour):
            if behaviour == "boom":
                raise RuntimeError("boom")
            return _listing("a")
        monkeypatch.setattr(session.manager, "list_tools", probe_list)
        out = await mcp_service.check_health(1)
        async with execution_db() as db:
            row = await db.get(MCPServer, 1)
        assert (row.state, row.last_error, row.health_status) == ("failed", cause, None), behaviour
        assert out["last_error"] == cause and sm.safe_reason(row.last_error) == cause


async def test_a_probe_never_replaces_a_first_start_plan(execution_db, own_supervisor, monkeypatch):
    """F2 (review P5): a probe while a `first` plan sleeps between its attempts — no session, no
    attempt — has nothing to time out on and never replaces that plan."""
    await _seed(execution_db, state="starting", status="connecting")
    monkeypatch.setattr(mcp_service, "_HEALTH_PROBE_TIMEOUT", 0.05)
    plans = []
    real_new_plan = own_supervisor._new_plan

    def record(sid, plan):
        plans.append(plan)
        return real_new_plan(sid, plan)
    monkeypatch.setattr(own_supervisor, "_new_plan", record)
    own_supervisor.running = True                 # schedule() acts; no loop, no boot
    sleeper = asyncio.create_task(asyncio.sleep(3600))
    own_supervisor._inflight[1] = sleeper        # a first plan between attempts: no _attempt_fut

    async def wedged(server, cursor=None):
        await asyncio.sleep(5)
    monkeypatch.setattr(session.manager, "list_tools", wedged)
    try:
        out = await mcp_service.check_health(1)
        await asyncio.sleep(0)
        assert plans == [] and not sleeper.cancelled() and out["state"] == "starting"
    finally:
        own_supervisor.running = False
        if own_supervisor._inflight.get(1) is sleeper:
            del own_supervisor._inflight[1]
        sleeper.cancel()
        await asyncio.gather(sleeper, return_exceptions=True)


async def test_switching_on_follows_the_state_not_only_a_cached_session(execution_db, monkeypatch):
    """F2: `set_enabled(on)` returns early only for a server that is `starting` or `ready`. A
    session its state does not account for (any path that cached one for an `off` server) is
    replaced by a fresh start, never taken for "already running"."""
    await _seed(execution_db, state="off", status="connected", host_allowed=False)
    _live_session(monkeypatch, 1, "stray")
    scheduled = []
    monkeypatch.setattr(sm.supervisor, "schedule", lambda sid, **kw: scheduled.append((sid, kw)))
    await mcp_service.set_host_allowed(1, True)
    async with execution_db() as db:
        assert (await db.get(MCPServer, 1)).state == "starting"
    assert scheduled == [(1, {"fresh": True})]

    async with execution_db() as db:              # running and ready: switching on again is a no-op
        (await db.get(MCPServer, 1)).state = "ready"
        await db.commit()
    scheduled.clear()
    await mcp_service.set_host_allowed(1, True)
    async with execution_db() as db:
        assert (await db.get(MCPServer, 1)).state == "ready"
    assert scheduled == []


async def test_a_tool_error_echoing_the_servers_key_is_masked_wherever_it_goes(execution_db, monkeypatch):
    """F3 (review I-2, P4): the executor masks both failure texts — a tool's own error and a failed
    call — before it stores them and before the model reads them. The server's own key reaches
    neither mcp_servers.last_error, the server list, the Capabilities rows, the /connect fallback
    nor the tool result in plain form."""
    from server.mcp import executor
    secret = "-".join(["s3cr3t", "value", "789"])
    await _seed(execution_db, transport="http", command="", url="https://example.test/mcp", state="ready",
                status="connected", env=crypto.encrypt(json.dumps({"API_KEY": secret})))

    async def tool_error(server, name, args):
        return SimpleNamespace(isError=True, content=[SimpleNamespace(text=f"invalid key {secret}")])

    async def call_failed(server, name, args):
        raise RuntimeError(f"upstream rejected {secret}")
    for fake, said in ((tool_error, "invalid key ****"), (call_failed, "upstream rejected ****")):
        monkeypatch.setattr(session.manager, "call_tool", fake)
        out = await executor.MCPProxyExecutor(1, "t").execute({})
        assert out["ok"] is False and said in out["error"] and secret not in out["error"]
        async with execution_db() as db:
            stored = (await db.get(MCPServer, 1)).last_error
        assert said in stored and secret not in stored
    async with execution_db() as db:
        (await db.get(MCPServer, 1)).status = "error"          # a row the Capabilities page details
        await db.commit()
    (listed,) = await mcp_service.list_servers()
    rows = {r["key"]: r for r in await capability_list._mcp_rows()}
    served = [listed["last_error"], rows["mcp:1"]["detail"], await mcp_service.last_error_text(1)]
    assert all("****" in text and secret not in text for text in served)


async def test_the_boot_reset_retry_spares_a_ready_this_process_wrote(execution_db, own_supervisor, monkeypatch):
    """F4 (R2, review P6): the retry's "since" is the boot, not each try — a `ready` this process
    wrote after the failed reset, before the retry fired, stands."""
    await _seed(execution_db, 1, state="ready", status="connected")       # the last run's ready
    real_reset, calls = own_supervisor.reset_for_boot, []

    async def flaky(**kw):
        calls.append(kw)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return await real_reset(**kw)
    monkeypatch.setattr(own_supervisor, "reset_for_boot", flaky)
    monkeypatch.setattr(sm, "BOOT_RESET_RETRY_S", (1.0,))
    monkeypatch.setattr(own_supervisor, "start", lambda **kw: None)
    monkeypatch.setenv("ARSLAN_MCP_SUPERVISOR", "1")
    assert await main._start_mcp_supervisor() is True

    async def ok(server, cursor=None):
        return _listing("a")
    monkeypatch.setattr(session.manager, "list_tools", ok)
    assert (await asyncio.wait_for(own_supervisor.restart(1), 5)).state == "ready"   # before the retry
    await _background_done(own_supervisor)
    assert len(calls) == 2
    async with execution_db() as db:
        assert (await db.get(MCPServer, 1)).state == "ready"


async def test_the_forgotten_prune_line_is_thirty_days(monkeypatch, tmp_path):
    """F4 (R3, review P7): the 30-day line, within an hour on either side."""
    from server.services import capability_install
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    forgotten = tmp_path / "mcp" / ".forgotten"
    now = sm._utcnow()
    older = forgotten / f"1-{(now - timedelta(days=30, hours=1)).strftime('%Y%m%dT%H%M%S%fZ')}"
    newer = forgotten / f"2-{(now - timedelta(days=29, hours=23)).strftime('%Y%m%dT%H%M%S%fZ')}"
    for folder in (older, newer):
        folder.mkdir(parents=True)
    trashed = []
    monkeypatch.setattr(capability_install, "to_trash", lambda path: trashed.append(path.name))
    assert session.prune_forgotten() == [older.name] and trashed == [older.name]


async def test_a_starts_own_drop_waking_a_probe_never_reschedules(execution_db, own_supervisor, monkeypatch):
    """F4 (R4, review P9): a Connect's deliberate drop wakes the probe pending on the old session;
    the generation moved, so the probe schedules nothing over the start that is running."""
    await _seed(execution_db, state="ready", status="connected")
    pending = asyncio.Event()

    class _Blocking:
        async def list_tools(self, params=None):
            pending.set()
            await asyncio.Event().wait()
    _live_session(monkeypatch, 1, _Blocking())
    monkeypatch.setattr(mcp_service, "_HEALTH_PROBE_TIMEOUT", 5.0)

    async def open_(server):
        return _Live(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", open_)
    scheduled = []
    monkeypatch.setattr(own_supervisor, "schedule", lambda sid, **kw: scheduled.append((sid, kw)))
    probe = asyncio.create_task(mcp_service.check_health(1))
    await asyncio.wait_for(pending.wait(), 5)
    result = await asyncio.wait_for(own_supervisor.restart(1), 5)        # a Connect: drops first
    await asyncio.wait_for(probe, 5)
    async with execution_db() as db:
        row = await db.get(MCPServer, 1)
    assert result.state == "ready" and scheduled == [] and (row.state, row.last_error) == ("ready", None)


async def test_an_install_test_survives_one_overtaken_start(execution_db, own_supervisor, monkeypatch):
    """F4 (R34, review P10): the install test also starts an overtaken start once more (start_now):
    new folders while its start opens never fail the install."""
    from datetime import datetime

    from server.db.models import CapabilitySource
    from server.services import capability_flow
    await _seed(execution_db, 5, host_allowed=False, state="off")
    async with execution_db() as db:
        db.add(CapabilitySource(id="src5", kind="mcp", name="x", candidate_id="c", runtime="uv", needs={},
                                grants={}, state="installed", mcp_server_id=5, created_at=datetime.utcnow()))
        await db.commit()
    opens, first_open, release = [], asyncio.Event(), asyncio.Event()

    async def open_(server):
        opens.append(server["id"])
        if len(opens) == 1:
            first_open.set()
            await release.wait()
        return _Live(), SimpleNamespace(aclose=_closed)
    monkeypatch.setattr(session.manager, "_open_session", open_)
    test = asyncio.create_task(capability_flow.test_mcp("src5"))
    try:
        await asyncio.wait_for(first_open.wait(), 5)
        await session.manager.drop(5)
    finally:
        release.set()
    out = await asyncio.wait_for(test, 5)
    assert out["ok"] is True and opens == [5, 5]


def test_masking_never_raises_on_a_url_secret_forms_refuses():
    """F4 (R51, review P12): mask_for never raises, also for a malformed URL secret_forms refuses —
    and still masks both the URL's and the env's secrets."""
    secret = "-".join(["s3cr3t", "value", "321"])
    other = "-".join(["other", "secret", "1"])
    out = sm.mask_for({"url": f"http://[::1/mcp?token={secret}", "env": {"K": other}},
                      f"bad {secret} and {other}")
    assert secret not in out and other not in out


async def test_the_boot_reset_is_retried_until_it_succeeds(execution_db, own_supervisor, monkeypatch):
    """F4 (R53, review P13): a failed boot reset is retried more than once (1/2/4/8/16 s), not only
    once."""
    await _seed(execution_db, 1, state="ready", status="connected")
    real_reset, calls = own_supervisor.reset_for_boot, []

    async def flaky(**kw):
        calls.append(kw)
        if len(calls) <= 3:
            raise RuntimeError("database is locked")
        return await real_reset(**kw)
    monkeypatch.setattr(own_supervisor, "reset_for_boot", flaky)
    monkeypatch.setattr(sm, "BOOT_RESET_RETRY_S", (0.0, 0.0, 0.0, 0.0, 0.0))
    monkeypatch.setattr(own_supervisor, "start", lambda **kw: None)
    monkeypatch.setenv("ARSLAN_MCP_SUPERVISOR", "1")
    assert await main._start_mcp_supervisor() is True
    await _background_done(own_supervisor)
    async with execution_db() as db:
        assert len(calls) == 4 and (await db.get(MCPServer, 1)).state == "starting"


async def test_boot_never_waits_for_the_forgotten_prune_and_logs_its_failure(own_supervisor, monkeypatch, caplog):
    """F5 (review M-4): moving folders to the Trash may copy across volumes, so boot starts the
    prune in the background and never waits for it; a failure is logged, never raised."""
    began, release = threading.Event(), threading.Event()

    def slow_failing_prune():
        began.set()
        release.wait(5)
        raise OSError("the Trash is not writable")
    monkeypatch.setattr(session, "prune_forgotten", slow_failing_prune)

    async def reset():
        return None
    monkeypatch.setattr(own_supervisor, "reset_for_boot", reset)
    monkeypatch.setattr(own_supervisor, "start", lambda **kw: None)
    monkeypatch.setenv("ARSLAN_MCP_SUPERVISOR", "1")
    with caplog.at_level(logging.WARNING, logger="server.main"):
        try:
            assert await asyncio.wait_for(main._start_mcp_supervisor(), 2) is True   # not held up
            assert await asyncio.to_thread(began.wait, 5)
        finally:
            release.set()
        await _boot_background_done()
    assert "forgotten folders to the Trash failed" in caplog.text
