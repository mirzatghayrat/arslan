"""PB-4 MCP equipment health: migration 0027 (the health columns) and the dispatch advisory that
reads them. The on-demand probe (POST /mcp/{id}/health) and the boot sweep were removed in C2e-2:
the supervisor keeps the columns."""

import pytest_asyncio
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


async def test_build_spawn_system_appends_advisory_for_failing_server(maker, monkeypatch):
    """End-to-end wiring: a spawn equipped with a wired mcp_* tool on a server whose health probe
    failed gets exactly one advisory line inside its assembled system prompt.

    0.1.61 Task 8: a spawn is offered a server's tools only while it is ready in this process
    (`supervisor.ready_now`), so this is a server whose probe failed (e.g. it timed out) while its
    session is still live — a server that is not ready offers the spawn nothing at all."""
    from types import SimpleNamespace

    from server.db.models import Spawn, SpawnCapability, Tool, Toolset
    from server.mcp import session
    from server.orchestrator.dispatcher import build_spawn_system
    sid = await _seed_server(maker, health="failing")
    monkeypatch.setattr(session.manager, "_sessions", {sid: (object(), SimpleNamespace(aclose=None))})
    async with maker() as s:
        (await s.get(MCPServer, sid)).state = "ready"
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
