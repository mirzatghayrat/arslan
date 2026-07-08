import anyio
import pytest
from server.mcp import session as sess


class _ACM:
    def __init__(self, ret): self._ret = ret
    async def __aenter__(self): return self._ret
    async def __aexit__(self, *a): return False


class _Sess:
    def __init__(self, *a): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def initialize(self): self.inited = True


@pytest.fixture
def stub_sdk(monkeypatch):
    import mcp
    import mcp.client.stdio as sstdio
    import mcp.client.streamable_http as shttp
    calls = {}
    def fake_stdio(params):
        calls["stdio"] = params
        return _ACM(("r", "w"))
    def fake_http(url, headers=None):
        calls["http"] = (url, headers)
        return _ACM(("r", "w", "sid"))
    monkeypatch.setattr(sstdio, "stdio_client", fake_stdio)
    monkeypatch.setattr(shttp, "streamablehttp_client", fake_http)
    monkeypatch.setattr(mcp, "ClientSession", _Sess)
    return calls


def test_open_session_stdio_branch(stub_sdk):
    mgr = sess.MCPSessionManager()
    async def _run():
        await mgr._open_session({"id": 1, "transport": "stdio", "command": "npx", "args": ["-y", "x"], "env": {}})
    anyio.run(_run)
    assert stub_sdk["stdio"].command == "npx"        # StdioServerParameters built for stdio
    assert "http" not in stub_sdk


def test_open_session_http_branch(stub_sdk):
    mgr = sess.MCPSessionManager()
    async def _run():
        await mgr._open_session({"id": 2, "transport": "http", "url": "https://x/mcp",
                                 "env": {"Authorization": "Bearer t"}})
    anyio.run(_run)
    assert stub_sdk["http"] == ("https://x/mcp", {"Authorization": "Bearer t"})   # url + headers (env)
    assert "stdio" not in stub_sdk


def test_runtime_dict_includes_transport_url(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'rt.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _run():
        from server.db.models import Base, MCPServer
        from server import crypto
        from server.mcp.discovery import runtime_dict
        import json
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            srv = MCPServer(id=3, label="h", transport="http", command="", args=[],
                            url="https://y/mcp", env=crypto.encrypt(json.dumps({"K": "V"})), status="registered")
            s.add(srv)
            await s.commit()
            return runtime_dict(srv)
    d = anyio.run(_run)
    assert d["transport"] == "http" and d["url"] == "https://y/mcp" and d["env"] == {"K": "V"}
