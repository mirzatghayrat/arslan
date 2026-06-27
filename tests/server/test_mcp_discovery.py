import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer, Tool, Toolset


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        async with m() as s:
            s.add(MCPServer(id=1, label="fs", command="x", args=[], env=None, status="registered"))
            await s.commit()
    anyio.run(_seed)
    return m


def test_suggest_tier():
    from server.mcp.discovery import suggest_tier
    assert suggest_tier("read_file") == "safe"
    assert suggest_tier("search_docs") == "safe"
    assert suggest_tier("delete_file") == "orchestrator"
    assert suggest_tier("write_config") == "orchestrator"
    assert suggest_tier("frobnicate") == "orchestrator"     # unknown → conservative


def test_connect_and_discover_naturalizes(maker, monkeypatch):
    from server.mcp import discovery, session

    class _T:
        def __init__(self, n, d, s): self.name, self.description, self.inputSchema = n, d, s
    class _L:
        def __init__(self, tools): self.tools = tools
    async def fake_list(server):
        return _L([_T("read_file", "Read a file", {"type": "object"}),
                   _T("delete_file", "Delete a file", {"type": "object"})])
    monkeypatch.setattr(session.manager, "list_tools", fake_list)

    async def _run():
        out = await discovery.connect_and_discover(1)
        async with maker() as s:
            ts = (await s.execute(select(Toolset).where(Toolset.key == "mcp_1"))).scalar_one()
            tools = (await s.execute(select(Tool).where(Tool.toolset_key == "mcp_1").order_by(Tool.key))).scalars().all()
            srv = await s.get(MCPServer, 1)
        return out, ts, tools, srv

    out, ts, tools, srv = anyio.run(_run)
    assert ts.tier == "orchestrator" and ts.status == "registered"     # server toolset locked
    assert len(tools) == 2
    keys = {t.key for t in tools}
    assert "mcp_1__read_file" in keys and "mcp_1__delete_file" in keys
    for t in tools:
        assert t.tier == "orchestrator" and t.status == "registered"   # tools locked by default
        assert t.external_name in ("read_file", "delete_file")
        assert t.input_schema == {"type": "object"}
    assert srv.status == "connected"
    assert len(out) == 2


def test_discover_marks_error_on_failure(maker, monkeypatch):
    from server.mcp import discovery, session
    async def boom(server): raise RuntimeError("cannot launch npx")
    monkeypatch.setattr(session.manager, "list_tools", boom)

    async def _run():
        with pytest.raises(RuntimeError):
            await discovery.connect_and_discover(1)
        async with maker() as s:
            srv = await s.get(MCPServer, 1)
        return srv
    srv = anyio.run(_run)
    assert srv.status == "error" and "npx" in (srv.last_error or "")
