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
    def fake_http(url, headers=None, auth=None):
        calls["http"] = (url, headers)
        calls["auth"] = auth
        return _ACM(("r", "w", "sid"))
    monkeypatch.setattr(sstdio, "stdio_client", fake_stdio)
    # Patch the seam SESSION holds, not the SDK module: session.py imports the
    # symbol at module level now (so the oauth wiring could be tested the same
    # way), and a patch on the SDK module no longer reaches the copied binding.
    monkeypatch.setattr(shttp, "streamablehttp_client", fake_http)
    monkeypatch.setattr(sess, "streamablehttp_client", fake_http)

    # No stored tokens in this stub world — and no database either, so the real
    # has_tokens (a DB query) must not run.
    from server.mcp import oauth_flow

    async def no_tokens(server_id):
        return False
    monkeypatch.setattr(oauth_flow, "has_tokens", no_tokens)
    monkeypatch.setattr(mcp, "ClientSession", _Sess)
    return calls


async def test_open_session_stdio_branch(stub_sdk, monkeypatch):
    # Resolution has its own contract tests (test_mcp_spawn_env); this test pins
    # the BRANCH wiring, so resolution is stubbed to identity.
    from server.mcp import spawn_env
    monkeypatch.setattr(spawn_env, "resolve_command", lambda c: c)
    monkeypatch.setattr(spawn_env, "merged_path", lambda: "/usr/bin")
    mgr = sess.MCPSessionManager()
    await mgr._open_session({"id": 1, "transport": "stdio", "command": "npx", "args": ["-y", "x"], "env": {}})
    assert stub_sdk["stdio"].command == "npx"        # StdioServerParameters built for stdio
    assert "http" not in stub_sdk


async def test_open_session_http_branch(stub_sdk):
    mgr = sess.MCPSessionManager()
    await mgr._open_session({"id": 2, "transport": "http", "url": "https://x/mcp",
                             "env": {"Authorization": "Bearer t"}})
    assert stub_sdk["http"] == ("https://x/mcp", {"Authorization": "Bearer t"})   # url + headers (env)
    assert stub_sdk["auth"] is None          # tokenless server: today's request, byte for byte
    assert "stdio" not in stub_sdk


async def test_runtime_dict_includes_transport_url(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'rt.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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
        d = runtime_dict(srv)
    assert d["transport"] == "http" and d["url"] == "https://y/mcp" and d["env"] == {"K": "V"}
