"""ListMyCapabilitiesExecutor: Arslan reports its OWN usable capabilities from real data.

The v0.1.23 field report exposed two honesty gaps in this executor. `builtin`
was a hand-copied list that had already drifted (recall/remember missing —
the SLOT_KEYS lesson: derive, never enumerate). And `mcp` reported only
{label, status}, so with servers connected but their tools not yet equipped
(wired + host_enabled, both default OFF by the execute-closed ruling), Arslan
could not see WHY nothing was callable and guessed wrong at the user for
three turns. The contract pinned here: builtin derives from the live host
tool list, and each server reports its tools split into usable-by-me vs
not-yet-equipped, with an actionable note when everything is unequipped.

0.1.61 §B1/§B2 replaced the equip note: each server reports its one state, and its tools are
usable only when it is ready in this process (`supervisor.ready_now`: the row says `ready` AND
the session manager holds a live session) — the same rule that decides which tools the model is
offered. Every other server says why (the first line of its classified last_error) and what fixes
it.
"""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server import crypto
from server.db.models import Base, MCPServer, Tool, Toolset
from server.mcp import session
from server.mcp import supervisor as sm
from server.registry.executors import EXECUTORS, ListMyCapabilitiesExecutor


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'caps.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    monkeypatch.setattr(session.manager, "_sessions", {})    # no live session left by another test
    yield m
    await engine.dispose()


async def _closed():
    return None


def _live(monkeypatch, sid=1):
    """`sid`'s live session, cached as the manager caches one (no fingerprint: used as it is)."""
    monkeypatch.delitem(session.manager._fingerprints, sid, raising=False)
    monkeypatch.setitem(session.manager._sessions, sid, (object(), SimpleNamespace(aclose=_closed)))


async def _seed_server(m, *, status="connected", state="ready", host_allowed=True, tools=()):
    async with m() as s:
        s.add(MCPServer(id=1, label="playwright", command="npx", status=status, state=state,
                        host_allowed=host_allowed))
        s.add(Toolset(key="mcp_1", name="playwright", description="MCP server: playwright",
                      tier="orchestrator", status="registered"))
        for name, wired, host in tools:
            s.add(Tool(key=f"mcp_1__{name}", toolset_key="mcp_1", external_name=name,
                       description=name, tier="safe" if wired else "orchestrator",
                       status="wired" if wired else "registered", host_enabled=host))
        await s.commit()


async def test_builtin_is_derived_from_the_live_host_tool_list(maker):
    out = await ListMyCapabilitiesExecutor().execute({})
    assert out["ok"] is True
    keys = {b["key"] for b in out["builtin"]}
    # recall/remember are host tools TODAY — the hand-copied list had lost them.
    assert {"web_search", "web_extract", "render_chart", "recall", "remember"} <= keys
    assert "run_command" in keys                         # 0.1.48: the terminal is on by default
    assert not any(k.startswith("mcp_") for k in keys)   # mcp rides in its own section


async def test_equipped_mcp_tool_is_not_misfiled_into_builtin(maker):
    await _seed_server(maker, tools=[("browser_click", True, True)])
    out = await ListMyCapabilitiesExecutor().execute({})
    assert not any(b["key"].startswith("mcp_") for b in out["builtin"])


async def test_host_allowed_server_reports_every_tool_usable(maker, monkeypatch):
    """Server-level ruling (2026-08-18): connect = usable by Arslan. Per-tool
    wire/host states no longer split the host dimension."""
    _live(monkeypatch)                                  # ready in this process: row + live session
    await _seed_server(maker, tools=[
        ("browser_click", True, True),
        ("browser_navigate", True, False),
        ("browser_snapshot", False, False),
    ])
    out = await ListMyCapabilitiesExecutor().execute({})
    (srv,) = out["mcp"]
    assert srv["label"] == "playwright" and srv["status"] == "connected"
    assert srv["tool_count"] == 3
    assert srv["usable_by_me"] == ["browser_click", "browser_navigate", "browser_snapshot"]
    assert srv["host_allowed"] is True
    assert srv["state"] == "ready"
    assert "reason" not in srv and "fix" not in srv    # nothing to explain or fix
    assert "last_error" not in srv                      # none stored, none shown


async def test_a_switched_off_server_says_so_and_offers_nothing(maker):
    await _seed_server(maker, host_allowed=False, state="off", tools=[("browser_click", False, False)])
    async with maker() as s:                            # an old failure is not why it is off
        (await s.get(MCPServer, 1)).last_error = "the server exited during start (code 1)"
        await s.commit()
    out = await ListMyCapabilitiesExecutor().execute({})
    (srv,) = out["mcp"]
    assert srv["usable_by_me"] == [] and srv["state"] == "off"
    assert srv["fix"] == "switched off; it can be switched on in Capabilities"
    assert "reason" not in srv                          # not given as why it is off …
    assert srv["last_error"] == "the server exited during start (code 1)"      # … but still visible
    assert "note" not in out                           # the stale "Capabilities → MCPS" note is gone


async def test_a_server_left_off_by_a_failed_install_test_is_not_blamed_on_the_user(maker):
    """Review I-1 (probe P5): installs are created `off`, and a failed install test leaves them so
    (`capability_flow.test_mcp`). The model must not be told the user turned it off, and the real
    failure must reach it: under its own key, not as why it is off."""
    await _seed_server(maker, status="error", state="off", host_allowed=False,
                       tools=[("browser_click", True, True)])
    async with maker() as s:
        (await s.get(MCPServer, 1)).last_error = "did not start within 120 s (waiting for tools/list)\nstderr…"
        await s.commit()
    (srv,) = (await ListMyCapabilitiesExecutor().execute({}))["mcp"]
    assert srv["state"] == "off" and srv["usable_by_me"] == [] and srv["tool_count"] == 1
    assert srv["last_error"] == "did not start within 120 s (waiting for tools/list)"
    assert "switched off" in srv["fix"] and "reason" not in srv
    assert "the user" not in json.dumps(srv)


async def test_no_note_for_default_allowed_server(maker):
    await _seed_server(maker, tools=[("browser_click", False, False)])
    out = await ListMyCapabilitiesExecutor().execute({})
    assert "note" not in out                            # connect already granted host use


async def test_error_server_gets_no_equip_note(maker):
    """An errored server's problem is the connection, not the switches — the
    note must not send the user to the wrong surface."""
    await _seed_server(maker, status="error", state="failed", tools=[("browser_click", False, False)])
    out = await ListMyCapabilitiesExecutor().execute({})
    assert "note" not in out
    assert out["mcp"][0]["state"] == "failed" and "retries by itself" in out["mcp"][0]["fix"]


async def test_a_failed_servers_tools_are_not_usable_and_its_reason_is_given(maker):
    await _seed_server(maker, status="error", state="parked", tools=[("browser_click", True, True)])
    async with maker() as s:
        srv = await s.get(MCPServer, 1)
        srv.last_error = "command `npx` not found — install Node.js\nnpm ERR! enoent"
        await s.commit()
    out = await ListMyCapabilitiesExecutor().execute({})
    (srv,) = out["mcp"]
    assert srv["usable_by_me"] == [] and srv["tool_count"] == 1
    assert srv["reason"] == "command `npx` not found — install Node.js"
    assert srv["last_error"] == srv["reason"]
    # the cause is said once (the `reason`), not again inside the fix (review M-3)
    assert srv["fix"] == ("it is stopped until the cause is fixed; then the user can press Reconnect "
                          "in Capabilities")


# ── 0.1.61 Task 8: one readiness rule (carries.md "Task 8") ───────────────────────────────

async def test_a_ready_row_without_a_live_session_is_starting_and_offers_nothing(maker):
    """`ready` is ready in this process: the row AND a live session (`supervisor.ready_now`). The
    last run's `ready` (a failed boot reset), or one whose session died while its restart waits for a
    start slot, is not offered to the model — so the list must not call its tools usable, and says
    what a call to it is answered with: still starting."""
    await _seed_server(maker, tools=[("browser_click", True, True)])        # ready, no session cached
    out = await ListMyCapabilitiesExecutor().execute({})
    (srv,) = out["mcp"]
    assert srv["usable_by_me"] == [] and srv["tool_count"] == 1
    assert srv["state"] == "starting" and srv["status"] == "connected"
    assert srv["fix"] == "wait a moment; it is starting by itself"
    assert "reason" not in srv


async def test_a_failed_row_is_not_usable_even_with_a_session_still_cached(maker, monkeypatch):
    """The state counts as much as the session: a session that outlives its row's `failed` (the
    drop callback has not landed yet) is not a usable server."""
    _live(monkeypatch)
    await _seed_server(maker, status="error", state="failed", tools=[("browser_click", True, True)])
    (srv,) = (await ListMyCapabilitiesExecutor().execute({}))["mcp"]
    assert srv["usable_by_me"] == [] and srv["state"] == "failed"


async def test_a_switched_on_server_whose_row_still_says_off_is_starting_not_off(maker):
    """Task 7 review M-3: its `starting` write has not landed (or failed; the tick starts it). The
    user did not turn it off — never tell the model so."""
    await _seed_server(maker, state="off", host_allowed=True, tools=[("browser_click", True, True)])
    (srv,) = (await ListMyCapabilitiesExecutor().execute({}))["mcp"]
    assert srv["state"] == "starting" and srv["usable_by_me"] == []
    assert srv["fix"] == "wait a moment; it is starting by itself"


async def test_a_server_the_user_just_switched_off_is_off_before_its_state_says_so(maker, monkeypatch):
    """`set_host_allowed` commits the switch first and the supervisor writes `off` after: in between
    the row says `ready` with its session live, yet the host is already refused (`_arslan_tools`)."""
    _live(monkeypatch)
    await _seed_server(maker, host_allowed=False, state="ready", tools=[("browser_click", True, True)])
    (srv,) = (await ListMyCapabilitiesExecutor().execute({}))["mcp"]
    assert srv["state"] == "off" and srv["usable_by_me"] == [] and srv["host_allowed"] is False
    assert srv["fix"] == "switched off; it can be switched on in Capabilities"


async def test_a_starting_server_says_what_it_is_doing(maker, monkeypatch):
    await _seed_server(maker, status="connecting", state="starting", tools=[])
    monkeypatch.setitem(sm.supervisor._notes, 1, "downloading Node 24.21.0 (50 MB)")
    (srv,) = (await ListMyCapabilitiesExecutor().execute({}))["mcp"]
    assert srv["state"] == "starting" and srv["reason"] == "downloading Node 24.21.0 (50 MB)"
    assert srv["usable_by_me"] == []


async def test_a_failed_servers_next_try_is_given(maker):
    await _seed_server(maker, status="error", state="failed", tools=[("browser_click", True, True)])
    when = sm._utcnow() + timedelta(seconds=90)
    async with maker() as s:
        row = await s.get(MCPServer, 1)
        row.next_retry_at, row.last_error = when, "the server exited during start (code 1)"
        await s.commit()
    (srv,) = (await ListMyCapabilitiesExecutor().execute({}))["mcp"]
    assert srv["next_retry_at"] == when.isoformat()
    assert srv["fix"] == (f"it retries by itself (next try {when.isoformat()}); "
                          "the user can press Reconnect in Capabilities")
    assert srv["reason"] == "the server exited during start (code 1)"


async def test_the_fix_for_a_server_that_needs_auth_asks_what_it_is_asked_to_do(maker):
    """A server with a key or header is asked to re-check it; one without signs in. A saved sign-in
    that expired (OAuth) is a sign-in even for a server that also sends headers (Task 7 re-review
    R5) — the same rule `executor.state_words` and the status line follow."""
    await _seed_server(maker, status="error", state="needs_auth", tools=[("t", True, True)])
    sign_in = "the user must sign in from Capabilities (Authorize)"
    recheck = "re-check the key/token on this server in Capabilities"

    async def fix(*, env, last_error):
        async with maker() as s:
            row = await s.get(MCPServer, 1)
            row.env = crypto.encrypt(json.dumps(env)) if env else None
            row.last_error = last_error
            await s.commit()
        return (await ListMyCapabilitiesExecutor().execute({}))["mcp"][0]["fix"]

    assert await fix(env={}, last_error="HTTP 401 Unauthorized") == sign_in
    assert await fix(env={"API_KEY": "k-12345"}, last_error="HTTP 401 Unauthorized") == recheck
    assert await fix(env={"API_KEY": "k-12345"}, last_error=f"{sm.SIGN_IN_PREFIX} expired") == sign_in


async def test_a_long_reason_is_cut_at_200_characters(maker):
    """Review M-4: the model-sized payload — the reason and the stored error line are cut at 200."""
    await _seed_server(maker, status="error", state="failed", tools=[("t", True, True)])
    async with maker() as s:
        (await s.get(MCPServer, 1)).last_error = "x" * 300 + "\nsecond line"
        await s.commit()
    (srv,) = (await ListMyCapabilitiesExecutor().execute({}))["mcp"]
    assert srv["reason"] == "x" * 200 and srv["last_error"] == "x" * 200


async def test_the_reason_and_the_stored_error_never_carry_the_servers_own_secret(maker):
    """Review M-5: a pre-0.1.61 `failed` row can hold an unmasked error until the boot reset ends. The
    server's own key is masked in both lines — before the line is cut, so a key straddling the cut
    is masked whole, never left with its head."""
    secret = "-".join(["s3cr3t", "value", "789"])
    await _seed_server(maker, status="error", state="failed", tools=[("t", True, True)])
    async with maker() as s:
        row = await s.get(MCPServer, 1)
        row.env = crypto.encrypt(json.dumps({"API_KEY": secret}))
        row.last_error = f"invalid key {secret}\nmore"
        await s.commit()
    (srv,) = (await ListMyCapabilitiesExecutor().execute({}))["mcp"]
    assert srv["reason"] == "invalid key ****" and srv["last_error"] == "invalid key ****"
    async with maker() as s:
        (await s.get(MCPServer, 1)).last_error = "a" * 196 + secret + " tail"       # straddles the cut
        await s.commit()
    (srv,) = (await ListMyCapabilitiesExecutor().execute({}))["mcp"]
    assert srv["reason"] == "a" * 196 + "****" and srv["last_error"] == srv["reason"]
    assert secret[:4] not in json.dumps(srv)


def test_registered_in_executors():
    assert EXECUTORS.get("list_my_capabilities").__class__ is ListMyCapabilitiesExecutor
