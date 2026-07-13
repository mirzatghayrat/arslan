import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer, Tool, Toolset


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'e.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(MCPServer(id=2, label="fs", command="x", args=[], env=None, status="connected"))
        s.add(Toolset(key="mcp_2", name="fs", description="d", tier="orchestrator", status="registered"))
        s.add(Tool(key="mcp_2__read_file", toolset_key="mcp_2", description="read",
                   tier="safe", status="wired", input_schema={}, external_name="read_file"))
        await s.commit()
    return m


class _Text:
    def __init__(self, t): self.type, self.text = "text", t
class _CallResult:
    def __init__(self, content, isError=False): self.content, self.isError = content, isError


async def test_proxy_executor_maps_result(maker, monkeypatch):
    from server.mcp import executor, session
    async def fake_call(server, name, args):
        assert name == "read_file" and args == {"path": "/a"}
        return _CallResult([_Text("file body")])
    monkeypatch.setattr(session.manager, "call_tool", fake_call)

    ex = executor.MCPProxyExecutor(server_id=2, external_name="read_file")
    res = await ex.execute({"path": "/a"})
    assert res["ok"] is True and "file body" in res["summary"]
    assert "external" not in res or res["external"] is not False   # must be wrap_external-framed


async def test_proxy_executor_error_result(maker, monkeypatch):
    from server.mcp import executor, session
    async def fake_call(server, name, args): return _CallResult([_Text("boom")], isError=True)
    monkeypatch.setattr(session.manager, "call_tool", fake_call)
    res = await executor.MCPProxyExecutor(server_id=2, external_name="read_file").execute({})
    assert res["ok"] is False and "boom" in res["error"]


async def test_resolve_executor_static_mcp_and_none(maker):
    from server.registry.executors import resolve_executor

    builtin = await resolve_executor("web_search")
    mcp = await resolve_executor("mcp_2__read_file")
    missing = await resolve_executor("mcp_2__nope")
    nonsense = await resolve_executor("not_a_tool")
    assert builtin is not None and builtin.key == "web_search"
    assert mcp.__class__.__name__ == "MCPProxyExecutor" and mcp.external_name == "read_file"
    assert missing is None and nonsense is None
