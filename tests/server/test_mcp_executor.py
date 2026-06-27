import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer, Tool, Toolset


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'e.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        async with m() as s:
            s.add(MCPServer(id=2, label="fs", command="x", args=[], env=None, status="connected"))
            s.add(Toolset(key="mcp_2", name="fs", description="d", tier="orchestrator", status="registered"))
            s.add(Tool(key="mcp_2__read_file", toolset_key="mcp_2", description="read",
                       tier="safe", status="wired", input_schema={}, external_name="read_file"))
            await s.commit()
    anyio.run(_seed)
    return m


class _Text:
    def __init__(self, t): self.type, self.text = "text", t
class _CallResult:
    def __init__(self, content, isError=False): self.content, self.isError = content, isError


def test_proxy_executor_maps_result(maker, monkeypatch):
    from server.mcp import executor, session
    async def fake_call(server, name, args):
        assert name == "read_file" and args == {"path": "/a"}
        return _CallResult([_Text("file body")])
    monkeypatch.setattr(session.manager, "call_tool", fake_call)

    async def _run():
        ex = executor.MCPProxyExecutor(server_id=2, external_name="read_file")
        return await ex.execute({"path": "/a"})
    res = anyio.run(_run)
    assert res["ok"] is True and "file body" in res["summary"]
    assert "external" not in res or res["external"] is not False   # must be wrap_external-framed


def test_proxy_executor_error_result(maker, monkeypatch):
    from server.mcp import executor, session
    async def fake_call(server, name, args): return _CallResult([_Text("boom")], isError=True)
    monkeypatch.setattr(session.manager, "call_tool", fake_call)
    async def _run():
        return await executor.MCPProxyExecutor(server_id=2, external_name="read_file").execute({})
    res = anyio.run(_run)
    assert res["ok"] is False and "boom" in res["error"]


def test_resolve_executor_static_mcp_and_none(maker):
    from server.registry.executors import resolve_executor

    async def _run():
        builtin = await resolve_executor("web_search")
        mcp = await resolve_executor("mcp_2__read_file")
        missing = await resolve_executor("mcp_2__nope")
        nonsense = await resolve_executor("not_a_tool")
        return builtin, mcp, missing, nonsense
    builtin, mcp, missing, nonsense = anyio.run(_run)
    assert builtin is not None and builtin.key == "web_search"
    assert mcp.__class__.__name__ == "MCPProxyExecutor" and mcp.external_name == "read_file"
    assert missing is None and nonsense is None
