import pytest
import pytest_asyncio
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
        # host-enabled + wired → Arslan gets it
        s.add(Tool(key="mcp_1__read", toolset_key="mcp_1", description="read", tier="orchestrator",
                   status="wired", input_schema={}, external_name="read", host_enabled=True))
        # wired but NOT host-enabled → Arslan does NOT get it
        s.add(Tool(key="mcp_1__list", toolset_key="mcp_1", description="list", tier="safe",
                   status="wired", input_schema={}, external_name="list", host_enabled=False))
        # host-enabled but NOT wired → Arslan does NOT get it
        s.add(Tool(key="mcp_1__write", toolset_key="mcp_1", description="write", tier="orchestrator",
                   status="registered", input_schema={}, external_name="write", host_enabled=True))
        await s.commit()
    return m


async def test_arslan_tools_include_only_host_enabled_wired(maker):
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    assert "web_search" in keys and "render_chart" in keys      # built-ins still present
    assert "mcp_1__read" in keys                                 # host_enabled + wired
    assert "mcp_1__list" not in keys                             # not host_enabled
    assert "mcp_1__write" not in keys                            # not wired


async def test_set_host_enabled_toggles(maker):
    from server.services import mcp_service
    from sqlalchemy import select

    await mcp_service.set_host_enabled("mcp_1__list", True)
    async with maker() as s:
        result = (await s.execute(select(Tool).where(Tool.key == "mcp_1__list"))).scalar_one().host_enabled
    assert result is True


async def test_set_host_enabled_rejects_non_mcp(maker):
    from server.services import mcp_service
    with pytest.raises(ValueError):
        await mcp_service.set_host_enabled("web_search", True)
