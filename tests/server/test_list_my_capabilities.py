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
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer, Tool, Toolset
from server.registry.executors import EXECUTORS, ListMyCapabilitiesExecutor


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'caps.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    yield m
    await engine.dispose()


async def _seed_server(m, *, status="connected", host_allowed=True, tools=()):
    async with m() as s:
        s.add(MCPServer(id=1, label="playwright", command="npx", status=status,
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
    assert "run_command" not in keys                     # shell defaults off
    assert not any(k.startswith("mcp_") for k in keys)   # mcp rides in its own section


async def test_equipped_mcp_tool_is_not_misfiled_into_builtin(maker):
    await _seed_server(maker, tools=[("browser_click", True, True)])
    out = await ListMyCapabilitiesExecutor().execute({})
    assert not any(b["key"].startswith("mcp_") for b in out["builtin"])


async def test_host_allowed_server_reports_every_tool_usable(maker):
    """Server-level ruling (2026-08-18): connect = usable by Arslan. Per-tool
    wire/host states no longer split the host dimension."""
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


async def test_host_disallowed_server_yields_actionable_note(maker):
    await _seed_server(maker, host_allowed=False, tools=[("browser_click", False, False)])
    out = await ListMyCapabilitiesExecutor().execute({})
    (srv,) = out["mcp"]
    assert srv["usable_by_me"] == [] and srv["host_allowed"] is False
    assert "note" in out
    assert "MCPS" in out["note"]                        # points at the server-level switch


async def test_no_note_for_default_allowed_server(maker):
    await _seed_server(maker, tools=[("browser_click", False, False)])
    out = await ListMyCapabilitiesExecutor().execute({})
    assert "note" not in out                            # connect already granted host use


async def test_error_server_gets_no_equip_note(maker):
    """An errored server's problem is the connection, not the switches — the
    note must not send the user to the wrong surface."""
    await _seed_server(maker, status="error", tools=[("browser_click", False, False)])
    out = await ListMyCapabilitiesExecutor().execute({})
    assert "note" not in out


def test_registered_in_executors():
    assert EXECUTORS.get("list_my_capabilities").__class__ is ListMyCapabilitiesExecutor
