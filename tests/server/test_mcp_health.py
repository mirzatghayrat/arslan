"""PB-4 MCP equipment health check: migration 0027, POST /mcp/{id}/health probe
(ok / failing / bounded-timeout), require_auth (条件3), boot sweep, dispatch advisory."""
import asyncio
import importlib

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer

# ── migration 0027 ──────────────────────────────────────────────────────────────


async def test_0027_adds_health_columns_and_is_idempotent():
    from server.db.migrations.versions._0027_mcp_health import upgrade_sync
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            # Legacy shape: mcp_servers WITHOUT the PB-4 columns → exercises the real ALTERs.
            await conn.exec_driver_sql(
                "CREATE TABLE mcp_servers (id INTEGER PRIMARY KEY, label VARCHAR(80), "
                "transport VARCHAR(20), command VARCHAR(255), args JSON, env TEXT, url VARCHAR(500), "
                "status VARCHAR(20), last_error TEXT, created_at DATETIME)")
            await conn.run_sync(upgrade_sync)
            await conn.run_sync(upgrade_sync)  # double-run: idempotent
            cols = {r[1] for r in (await conn.exec_driver_sql("PRAGMA table_info(mcp_servers)"))}
            assert {"last_checked_at", "health_status"} <= cols
    finally:
        await engine.dispose()


# ── endpoint probe paths ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'health.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    from server.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), m


class _T:
    def __init__(self, n):
        self.name, self.description, self.inputSchema = n, n, {}


class _L:
    def __init__(self, ts):
        self.tools = ts


class _FakeStack:
    async def aclose(self):
        pass


async def _add_server(c) -> int:
    r = await c.post("/api/v1/mcp/servers",
                     json={"label": "fetch", "command": "uvx", "args": ["mcp-server-fetch"], "env": {}})
    assert r.status_code == 200
    return r.json()["id"]


async def test_health_ok_path_writes_columns(client, monkeypatch):
    c, m = client
    from server.mcp import session

    async def fake_list(server):
        return _L([_T("fetch"), _T("fetch_html")])
    monkeypatch.setattr(session.manager, "list_tools", fake_list)
    monkeypatch.setattr(session.manager, "_proxy_sources", {})
    async with c:
        sid = await _add_server(c)
        r = await c.post(f"/api/v1/mcp/{sid}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["health_status"] == "ok" and body["tool_count"] == 2
    assert body["label"] == "fetch" and body["transport"] == "stdio"
    assert body["last_checked_at"] is not None
    assert body["last_error"] is None
    assert body["proxy_source"] == "unknown"       # session never launched this process: honest
    async with m() as s:
        srv = await s.get(MCPServer, sid)
    assert srv.health_status == "ok" and srv.last_checked_at is not None


async def test_health_ok_clears_stale_last_error_and_reports_proxy_source(client, monkeypatch):
    c, m = client
    from server.mcp import session

    async def fake_list(server):
        return _L([_T("fetch")])
    monkeypatch.setattr(session.manager, "list_tools", fake_list)
    async with c:
        sid = await _add_server(c)
        monkeypatch.setattr(session.manager, "_proxy_sources", {sid: "os.environ"})
        async with m() as s:
            srv = await s.get(MCPServer, sid)
            srv.last_error = "old failure"
            await s.commit()
        r = await c.post(f"/api/v1/mcp/{sid}/health")
    body = r.json()
    assert body["health_status"] == "ok"
    assert body["last_error"] is None              # column reflects the LATEST state
    assert body["proxy_source"] == "os.environ"    # PB-1 context surfaced
    async with m() as s:
        assert (await s.get(MCPServer, sid)).last_error is None


async def test_health_failing_path_persists_last_error(client, monkeypatch):
    c, m = client
    from server.mcp import session

    async def fake_list(server):
        raise RuntimeError("spawn failed: uvx not found")
    monkeypatch.setattr(session.manager, "list_tools", fake_list)
    async with c:
        sid = await _add_server(c)
        r = await c.post(f"/api/v1/mcp/{sid}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["health_status"] == "failing" and body["tool_count"] is None
    assert "health probe list_tools" in body["last_error"]    # PB-2 shape: stamp + context
    assert "uvx not found" in body["last_error"]
    async with m() as s:
        srv = await s.get(MCPServer, sid)
    assert srv.health_status == "failing" and "uvx not found" in srv.last_error


async def test_health_timeout_is_bounded_and_drops_session(client, monkeypatch):
    """条件3: the probe must never hang — wedged list_tools hits the wait_for bound,
    and the cached session is dropped explicitly (wait_for's CancelledError bypasses
    list_tools' own `except Exception` drop)."""
    c, m = client
    from server.mcp import session
    from server.services import mcp_service

    monkeypatch.setattr(mcp_service, "_HEALTH_PROBE_TIMEOUT", 0.05)

    async def wedged_list(server):
        await asyncio.sleep(5)
    monkeypatch.setattr(session.manager, "list_tools", wedged_list)
    async with c:
        sid = await _add_server(c)
        session.manager._sessions[sid] = ("fake-session", _FakeStack())
        r = await c.post(f"/api/v1/mcp/{sid}/health")
    body = r.json()
    assert body["health_status"] == "failing"
    assert "timed out" in body["last_error"]
    assert sid not in session.manager._sessions    # wedged subprocess can't poison later calls


async def test_health_unknown_server_404(client):
    c, _ = client
    async with c:
        r = await c.post("/api/v1/mcp/999/health")
    assert r.status_code == 404


async def test_health_requires_auth(client, monkeypatch):
    """条件3: the MCP router had NO auth at all; it now carries router-level require_auth,
    so /health (and every other MCP endpoint) rejects unauthenticated calls when a token is set."""
    c, _ = client
    import server.config as config
    monkeypatch.setenv("ARSLAN_API_TOKEN", "secret123")
    importlib.reload(config)
    try:
        async with c:
            r = await c.post("/api/v1/mcp/1/health")
            assert r.status_code == 401
            r = await c.get("/api/v1/mcp/servers")            # router-wide, not just /health
            assert r.status_code == 401
            r = await c.post("/api/v1/mcp/999/health",
                             headers={"Authorization": "Bearer secret123"})
            assert r.status_code == 404                       # authed → reaches the handler
    finally:
        monkeypatch.setenv("ARSLAN_API_TOKEN", "")
        importlib.reload(config)                              # never leak the token to later tests


# ── boot sweep (ARSLAN_MCP_HEALTH_ON_BOOT=1) ───────────────────────────────────


async def test_check_health_all_probes_every_server_fail_open(client, monkeypatch):
    c, m = client
    from server.mcp import session
    from server.services import mcp_service

    async def fake_list(server):
        if server["id"] % 2 == 1:
            raise RuntimeError("down")
        return _L([_T("fetch")])
    monkeypatch.setattr(session.manager, "list_tools", fake_list)
    async with c:
        sid1 = await _add_server(c)
        r = await c.post("/api/v1/mcp/servers",
                         json={"label": "fs", "command": "npx", "args": ["fs"], "env": {}})
        sid2 = r.json()["id"]
    await mcp_service.check_health_all()          # one bad server never blocks the next
    async with m() as s:
        s1, s2 = await s.get(MCPServer, sid1), await s.get(MCPServer, sid2)
    assert {s1.health_status, s2.health_status} == {"failing", "ok"}
    assert s1.last_checked_at is not None and s2.last_checked_at is not None


# ── dispatch advisory ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'adv.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def _seed_server(m, *, health: str | None) -> int:
    async with m() as s:
        srv = MCPServer(label="fetch", command="uvx", args=[], transport="stdio",
                        status="connected", health_status=health)
        s.add(srv)
        await s.commit()
        await s.refresh(srv)
        return srv.id


async def test_advisory_lists_failing_mcp_tools(maker):
    from server.orchestrator.dispatcher import _mcp_health_advisory
    sid = await _seed_server(maker, health="failing")
    wired = [{"key": f"mcp_{sid}__fetch", "description": "fetch a url", "input_schema": {}},
             {"key": "web_search", "description": "builtin", "input_schema": {}}]
    line = await _mcp_health_advisory(wired)
    assert f"mcp_{sid}__fetch" in line and "体检失败" in line and "内置工具" in line
    assert "web_search" not in line                       # builtins are never implicated


async def test_advisory_silent_when_healthy_or_unchecked(maker):
    from server.orchestrator.dispatcher import _mcp_health_advisory
    sid_ok = await _seed_server(maker, health="ok")
    sid_new = await _seed_server(maker, health=None)
    wired = [{"key": f"mcp_{sid_ok}__fetch", "description": "d", "input_schema": {}},
             {"key": f"mcp_{sid_new}__grep", "description": "d", "input_schema": {}}]
    assert await _mcp_health_advisory(wired) == ""
    assert await _mcp_health_advisory([{"key": "web_search", "description": "d"}]) == ""


async def test_advisory_fails_open_on_lookup_error(maker, monkeypatch):
    from server.orchestrator.dispatcher import _mcp_health_advisory

    def boom():
        raise RuntimeError("db gone")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", boom)
    wired = [{"key": "mcp_1__fetch", "description": "d", "input_schema": {}}]
    assert await _mcp_health_advisory(wired) == ""        # health lookup error → no line


async def test_build_spawn_system_appends_advisory_for_failing_server(maker):
    """End-to-end wiring: a spawn equipped with a wired mcp_* tool on a failing server
    gets exactly one advisory line inside its assembled system prompt."""
    from server.db.models import Spawn, SpawnCapability, Tool, Toolset
    from server.orchestrator.dispatcher import build_spawn_system
    sid = await _seed_server(maker, health="failing")
    async with maker() as s:
        s.add(Toolset(key=f"mcp_{sid}", name="fetch", description="MCP server: uvx",
                      tier="safe", status="registered"))
        s.add(Tool(key=f"mcp_{sid}__fetch", toolset_key=f"mcp_{sid}", description="fetch a url",
                   tier="safe", status="wired", input_schema={}, external_name="fetch"))
        s.add(Spawn(id=7, name="调研员", domain_category="research", system_prompt="You research."))
        s.add(SpawnCapability(spawn_id=7, kind="toolset", ref_key=f"mcp_{sid}"))
        await s.commit()
        spawn = await s.get(Spawn, 7)
    system, wired = await build_spawn_system(spawn, retrieval_query="x", current_turn=1)
    assert any(t["key"] == f"mcp_{sid}__fetch" for t in wired)
    assert f"注意:MCP 工具 mcp_{sid}__fetch 所属服务最近体检失败" in system
    assert "优先使用等价内置工具" in system
