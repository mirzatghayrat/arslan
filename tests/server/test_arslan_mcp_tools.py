"""Host access to MCP tools is SERVER-level (user ruling 2026-08-18).

connect is the human consent act: every discovered tool of a host_allowed
server reaches Arslan's tool list, per-tool wire/host_enabled no longer gate
the HOST dimension (they remain the spawn dimension's vocabulary). The
revocable face is `mcp_servers.host_allowed` — one switch per server.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer, Tool, Toolset


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'at.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(MCPServer(id=1, label="fs", command="x", args=[], env=None, status="connected"))
        s.add(Toolset(key="mcp_1", name="fs", description="d", tier="orchestrator", status="registered"))
        # Deliberately three different per-tool states — under the server-level
        # ruling NONE of them matters for the host dimension.
        s.add(Tool(key="mcp_1__read", toolset_key="mcp_1", description="read", tier="orchestrator",
                   status="wired", input_schema={"type": "object"}, external_name="read",
                   host_enabled=True))
        s.add(Tool(key="mcp_1__list", toolset_key="mcp_1", description="list", tier="safe",
                   status="wired", input_schema={}, external_name="list", host_enabled=False))
        s.add(Tool(key="mcp_1__write", toolset_key="mcp_1", description="write", tier="orchestrator",
                   status="registered", input_schema={}, external_name="write", host_enabled=False))
        await s.commit()
    return m


async def test_connected_server_gives_arslan_every_discovered_tool(maker):
    from server.orchestrator.arslan import _arslan_tools
    tools = {t["key"]: t for t in await _arslan_tools()}
    assert "web_search" in tools and "render_chart" in tools     # built-ins still present
    # Server-level ruling: all three, regardless of per-tool wire/host state.
    assert {"mcp_1__read", "mcp_1__list", "mcp_1__write"} <= set(tools)
    assert tools["mcp_1__read"]["input_schema"] == {"type": "object"}   # schema still carried


async def test_host_allowed_false_excludes_the_whole_server(maker):
    from server.orchestrator.arslan import _arslan_tools
    from server.services import mcp_service

    await mcp_service.set_host_allowed(1, False)
    keys = {t["key"] for t in await _arslan_tools()}
    assert not any(k.startswith("mcp_1__") for k in keys)
    assert "web_search" in keys                                   # built-ins unaffected

    await mcp_service.set_host_allowed(1, True)                   # revocable both ways
    keys = {t["key"] for t in await _arslan_tools()}
    assert "mcp_1__write" in keys


async def test_set_host_allowed_persists_and_lists(maker):
    from server.services import mcp_service

    await mcp_service.set_host_allowed(1, False)
    async with maker() as s:
        row = (await s.execute(select(MCPServer).where(MCPServer.id == 1))).scalar_one()
        assert row.host_allowed is False
    (srv,) = await mcp_service.list_servers()
    assert srv["host_allowed"] is False                           # _to_dict carries it


async def test_set_host_allowed_unknown_server_raises(maker):
    from server.services import mcp_service
    with pytest.raises(ValueError):
        await mcp_service.set_host_allowed(999, False)
