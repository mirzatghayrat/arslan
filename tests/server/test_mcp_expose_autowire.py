"""Expose ("Allow for spawns") auto-wires the read-graded tools.

Before this round the checkbox was half-fake: it lifted the Toolset to safe,
but the spawn choke point requires TOOL-level tier=safe ∧ status=wired
(service.py's assert_assignable), so a checked box still handed spawns
nothing. Now expose wires every tool whose suggested tier is safe — via
suggested_tier_for, so a hand-graded table (Playwright) wins over the verb
heuristic — and write-graded tools stay unwired: spawns never get write verbs
without an explicit per-tool action. Un-expose un-wires the server's tools
wholesale (user-approved default: no carve-out for manually wired ones).
"""
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer, Tool, Toolset


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ax.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def _seed(m, *, args=None, tools=()):
    async with m() as s:
        s.add(MCPServer(id=1, label="fs", command="x", args=args or [], env=None,
                        status="connected"))
        s.add(Toolset(key="mcp_1", name="fs", description="d",
                      tier="orchestrator", status="registered"))
        for name in tools:
            s.add(Tool(key=f"mcp_1__{name}", toolset_key="mcp_1", description=name,
                       tier="orchestrator", status="registered", input_schema={},
                       external_name=name))
        await s.commit()


async def _tool(m, name):
    async with m() as s:
        return (await s.execute(select(Tool).where(Tool.key == f"mcp_1__{name}"))).scalar_one()


async def test_expose_wires_read_graded_and_skips_write_graded(maker):
    from server.services import mcp_service
    await _seed(maker, tools=("read_file", "write_file", "frobnicate"))

    await mcp_service.set_exposed(1, True)

    read = await _tool(maker, "read_file")
    assert (read.tier, read.status) == ("safe", "wired")          # heuristic: read → safe
    write = await _tool(maker, "write_file")
    assert (write.tier, write.status) == ("orchestrator", "registered")   # write verbs never auto
    unknown = await _tool(maker, "frobnicate")
    assert unknown.status == "registered"                          # unknown → conservative
    async with maker() as s:
        ts = (await s.execute(select(Toolset).where(Toolset.key == "mcp_1"))).scalar_one()
    assert ts.tier == "safe"                                       # toolset lift unchanged


async def test_expose_respects_the_hand_graded_table(maker):
    """Playwright's names match no verb list; the hand table is authoritative —
    including its 'ungraded tool of a graded server → orchestrator' rule."""
    from server.mcp.catalog import PLAYWRIGHT_TOOL_TIERS
    from server.services import mcp_service

    safe_name = next(k for k, v in PLAYWRIGHT_TOOL_TIERS.items() if v == "safe")
    orch_name = next(k for k, v in PLAYWRIGHT_TOOL_TIERS.items() if v == "orchestrator")
    await _seed(maker, args=["-y", "@playwright/mcp@latest"],
                tools=(safe_name, orch_name, "browser_read_later"))

    await mcp_service.set_exposed(1, True)

    assert (await _tool(maker, safe_name)).status == "wired"
    assert (await _tool(maker, orch_name)).status == "registered"
    # read-verb name on a GRADED server: table wins, heuristic must NOT wire it
    assert (await _tool(maker, "browser_read_later")).status == "registered"


async def test_unexpose_unwires_wholesale(maker):
    from server.services import mcp_service
    await _seed(maker, tools=("read_file", "write_file"))
    await mcp_service.set_exposed(1, True)
    # user manually wired the write tool afterwards — approved default: no carve-out
    await mcp_service.wire_tool("mcp_1__write_file", "safe", True)

    await mcp_service.set_exposed(1, False)

    for name in ("read_file", "write_file"):
        t = await _tool(maker, name)
        assert (t.tier, t.status) == ("orchestrator", "registered"), name
    async with maker() as s:
        ts = (await s.execute(select(Toolset).where(Toolset.key == "mcp_1"))).scalar_one()
    assert ts.tier == "orchestrator"


async def test_list_servers_reports_real_exposed_state(maker):
    """The checkbox used to be write-only (frontend hardcoded exposed=false);
    the list now carries the toolset-derived truth."""
    from server.services import mcp_service
    await _seed(maker, tools=("read_file",))
    (srv,) = await mcp_service.list_servers()
    assert srv["exposed"] is False
    await mcp_service.set_exposed(1, True)
    (srv,) = await mcp_service.list_servers()
    assert srv["exposed"] is True
