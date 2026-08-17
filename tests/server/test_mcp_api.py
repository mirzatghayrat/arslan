import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Tool, Toolset


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'api.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    from server.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), m


async def test_create_list_masks_env(client):
    c, m = client
    async with c:
        r = await c.post("/api/v1/mcp/servers", json={"label": "fs", "command": "npx",
                                                       "args": ["-y", "x"], "env": {"TOKEN": "secret123"}})
        assert r.status_code == 200
        sid = r.json()["id"]
        lst = (await c.get("/api/v1/mcp/servers")).json()
    row = next(s for s in lst if s["id"] == sid)
    assert row["label"] == "fs" and row["command"] == "npx"
    assert row["env"].get("TOKEN") != "secret123"          # masked, never plaintext


async def test_connect_lists_tools_with_suggested_tier(client, monkeypatch):
    c, m = client
    from server.mcp import session
    class _T:
        def __init__(self, n): self.name, self.description, self.inputSchema = n, n, {}
    class _L:
        def __init__(self, ts): self.tools = ts
    async def fake_list(server): return _L([_T("read_file"), _T("delete_file")])
    monkeypatch.setattr(session.manager, "list_tools", fake_list)
    async with c:
        sid = (await c.post("/api/v1/mcp/servers", json={"label": "fs", "command": "x", "args": [], "env": {}})).json()["id"]
        await c.post(f"/api/v1/mcp/servers/{sid}/connect")
        tools = (await c.get(f"/api/v1/mcp/servers/{sid}/tools")).json()
    by = {t["name"]: t for t in tools}
    assert by["read_file"]["suggested_tier"] == "safe"
    assert by["delete_file"]["suggested_tier"] == "orchestrator"
    assert by["read_file"]["tier"] == "orchestrator" and by["read_file"]["status"] == "registered"   # locked


async def test_expose_and_wire_open_the_choke_point(client, monkeypatch):
    c, m = client
    from server.mcp import session
    class _T:
        def __init__(self, n): self.name, self.description, self.inputSchema = n, n, {}
    class _L:
        def __init__(self, ts): self.tools = ts
    async def fake_list(server): return _L([_T("read_file")])
    monkeypatch.setattr(session.manager, "list_tools", fake_list)
    async with c:
        sid = (await c.post("/api/v1/mcp/servers", json={"label": "fs", "command": "x", "args": [], "env": {}})).json()["id"]
        await c.post(f"/api/v1/mcp/servers/{sid}/connect")
        # before: locked → not assignable to spawns
        await c.patch(f"/api/v1/mcp/servers/{sid}/expose", json={"exposed": True})
        await c.patch(f"/api/v1/mcp/tools/mcp_{sid}__read_file/wire", json={"tier": "safe", "wired": True})
    async with m() as s:
        ts = (await s.execute(select(Toolset).where(Toolset.key == f"mcp_{sid}"))).scalar_one()
        tool = (await s.execute(select(Tool).where(Tool.key == f"mcp_{sid}__read_file"))).scalar_one()
    assert ts.tier == "safe"                       # exposed → equippable
    assert tool.tier == "safe" and tool.status == "wired"   # wired → reachable by wired_tools_for_spawn


async def test_host_toggle_endpoint(client, monkeypatch):
    c, m = client
    from server.mcp import session
    class _T:
        def __init__(self, n): self.name, self.description, self.inputSchema = n, n, {}
    class _L:
        def __init__(self, ts): self.tools = ts
    async def fake_list(server): return _L([_T("read")])
    monkeypatch.setattr(session.manager, "list_tools", fake_list)
    async with c:
        sid = (await c.post("/api/v1/mcp/servers", json={"label": "fs", "command": "x", "args": [], "env": {}})).json()["id"]
        await c.post(f"/api/v1/mcp/servers/{sid}/connect")
        r = await c.patch(f"/api/v1/mcp/tools/mcp_{sid}__read/host", json={"enabled": True})
        assert r.status_code == 200
        tools = (await c.get(f"/api/v1/mcp/servers/{sid}/tools")).json()
    assert next(t for t in tools if t["name"] == "read")["host_enabled"] is True


async def test_add_http_server_stores_url_transport(client):
    c, m = client
    async with c:
        r = await c.post("/api/v1/mcp/servers", json={"label": "remote", "transport": "http",
                                                       "url": "https://api.example/mcp", "command": "",
                                                       "args": [], "env": {"Authorization": "Bearer s3cr3t"}})
        assert r.status_code == 200
        row = r.json()
    assert row["transport"] == "http" and row["url"] == "https://api.example/mcp"
    assert row["env"].get("Authorization") != "Bearer s3cr3t"     # masked


async def test_reconnect_drops_cached_session(client, monkeypatch):
    c, m = client
    from server.mcp import session
    # seed a fake cached session for server id we will create
    async with c:
        sid = (await c.post("/api/v1/mcp/servers", json={"label": "fs", "command": "x", "args": [], "env": {}})).json()["id"]
        session.manager._sessions[sid] = ("fake-session", _FakeStackR())
        r = await c.post(f"/api/v1/mcp/servers/{sid}/reconnect")
        assert r.status_code == 200
    assert sid not in session.manager._sessions       # dropped


class _FakeStackR:
    async def aclose(self): pass


async def test_add_server_rejects_malformed_transport(client):
    c, m = client
    import pytest as _pytest

    from server.services import mcp_service
    with _pytest.raises(ValueError):
        await mcp_service.add_server("l", "x", [], {}, transport="ftp")          # bad transport
    with _pytest.raises(ValueError):
        await mcp_service.add_server("l", "", [], {}, transport="http", url="")  # http needs url
    with _pytest.raises(ValueError):
        await mcp_service.add_server("l", "", [], {}, transport="stdio")         # stdio needs command


async def test_add_server_dedup_stdio(client):
    """Adding the same stdio server (label+command+args) twice yields exactly one row."""
    c, m = client
    from server.services import mcp_service
    async with c:
        first = await mcp_service.add_server("myserver", "npx", ["-y", "tool"], {}, transport="stdio")
        second = await mcp_service.add_server("myserver", "npx", ["-y", "tool"], {}, transport="stdio")
    assert first["id"] == second["id"], "dedup guard must return the existing row, not insert a new one"
    # Verify only one row in DB
    from sqlalchemy import select
    from server.db.models import MCPServer
    async with m() as s:
        rows = (await s.execute(select(MCPServer).where(MCPServer.label == "myserver"))).scalars().all()
    assert len(rows) == 1


async def test_add_server_dedup_http(client):
    """Adding the same http server (label+url) twice yields exactly one row."""
    c, m = client
    from server.services import mcp_service
    async with c:
        first = await mcp_service.add_server("remote", "", [], {}, transport="http", url="https://mcp.example/api")
        second = await mcp_service.add_server("remote", "", [], {}, transport="http", url="https://mcp.example/api")
    assert first["id"] == second["id"], "dedup guard must return the existing row, not insert a new one"
    from sqlalchemy import select
    from server.db.models import MCPServer
    async with m() as s:
        rows = (await s.execute(select(MCPServer).where(MCPServer.label == "remote"))).scalars().all()
    assert len(rows) == 1


async def test_add_server_different_args_not_deduped(client):
    """Same label+command but different args are treated as distinct servers."""
    c, m = client
    from server.services import mcp_service
    async with c:
        first = await mcp_service.add_server("tool", "npx", ["-y", "toolA"], {}, transport="stdio")
        second = await mcp_service.add_server("tool", "npx", ["-y", "toolB"], {}, transport="stdio")
    assert first["id"] != second["id"], "different args must produce separate server entries"


async def test_connect_failure_returns_classified_502_not_500(client, monkeypatch):
    """The spawn/connect failure is already classified into last_error — the route
    must surface THAT text as a structured 502, not re-raise into a bare 500
    (the packaged app showed 'Error: HTTP 500' above a perfectly good per-server
    explanation)."""
    c, m = client
    from server.mcp import session

    async def fail(server):
        raise FileNotFoundError("command 'npx' was not found on PATH")
    monkeypatch.setattr(session.manager, "list_tools", fail)
    async with c:
        sid = (await c.post("/api/v1/mcp/servers", json={"label": "fs", "command": "npx",
                                                          "args": [], "env": {}})).json()["id"]
        r = await c.post(f"/api/v1/mcp/servers/{sid}/connect")
    assert r.status_code == 502
    assert "npx" in r.json()["detail"]            # the classified text, not a generic banner


async def test_connect_failure_with_empty_str_exc_uses_stored_classification(client, monkeypatch):
    """str(InvalidToken()) is the EMPTY string (spec ⓪ measured) — the route must
    fall back to the classified last_error, which _describe_failure guarantees is
    never blank. Discriminates the last_error_text lookup from a str(exc) echo."""
    c, m = client
    from server.mcp import session

    class _Mute(RuntimeError):
        def __str__(self):
            return ""

    async def fail(server):
        raise _Mute()
    monkeypatch.setattr(session.manager, "list_tools", fail)
    async with c:
        sid = (await c.post("/api/v1/mcp/servers", json={"label": "fs", "command": "npx",
                                                          "args": [], "env": {}})).json()["id"]
        r = await c.post(f"/api/v1/mcp/servers/{sid}/connect")
    assert r.status_code == 502
    assert r.json()["detail"] == "_Mute (no message)"   # the stored classification, verbatim


async def test_connect_unknown_server_is_404(client):
    c, m = client
    async with c:
        r = await c.post("/api/v1/mcp/servers/99999/connect")
    assert r.status_code == 404
