import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Tool, Toolset


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'api.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    anyio.run(_seed)
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
