"""0068: one state per MCP server and each tool's hints (0.1.61 §B1, §B4)."""
from sqlalchemy.ext.asyncio import create_async_engine

from server.db.migrations.versions._0068_mcp_state import upgrade_sync

# The pre-0068 shape the migration reads: mcp_servers from _0010 + _0027 + _0040, tools without
# annotations.
_PRE_0068 = (
    "CREATE TABLE mcp_servers (id INTEGER PRIMARY KEY, label VARCHAR(80) NOT NULL, "
    "transport VARCHAR(20) NOT NULL DEFAULT 'stdio', command VARCHAR(255) NOT NULL, "
    "args JSON NOT NULL, env TEXT, status VARCHAR(20) NOT NULL DEFAULT 'registered', "
    "last_error TEXT, created_at DATETIME, last_checked_at DATETIME, health_status VARCHAR(20), "
    "host_allowed BOOLEAN NOT NULL DEFAULT 1)",
    "CREATE TABLE tools (key VARCHAR(50) PRIMARY KEY, toolset_key VARCHAR(50) NOT NULL, "
    "description TEXT NOT NULL, tier VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL, "
    "input_schema JSON, external_name VARCHAR(120), host_enabled BOOLEAN NOT NULL DEFAULT 0)",
)
# (id, status, host_allowed): connected, error, the user's real rea row, a switched-off one.
_ROWS = ((1, "connected", 1), (2, "error", 1), (3, "disconnected", 1), (4, "connected", 0))


async def _legacy_db(path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        for ddl in _PRE_0068:
            await conn.exec_driver_sql(ddl)
        for sid, status, allowed in _ROWS:
            await conn.exec_driver_sql(
                "INSERT INTO mcp_servers (id, label, command, args, status, host_allowed) "
                "VALUES (?, ?, 'x', '[]', ?, ?)", (sid, f"s{sid}", status, allowed))
    return engine


async def _snapshot(engine):
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql(
            "SELECT id, state, fail_count, state_at, last_ok_at, next_retry_at "
            "FROM mcp_servers ORDER BY id")).all()
        servers = {r[1] for r in (await conn.exec_driver_sql("PRAGMA table_info(mcp_servers)")).all()}
        tools = {r[1] for r in (await conn.exec_driver_sql("PRAGMA table_info(tools)")).all()}
    return [tuple(r) for r in rows], servers, tools


async def test_0068_maps_every_legacy_status_and_is_idempotent(tmp_path):
    engine = await _legacy_db(tmp_path / "m.db")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_sync)
        first = await _snapshot(engine)
        rows, servers, tools = first
        assert {r[0]: r[1] for r in rows} == {1: "ready", 2: "failed", 3: "starting", 4: "off"}
        assert all(r[2] == 0 and r[3] is None and r[4] is None and r[5] is None for r in rows)
        assert {"state", "state_at", "last_ok_at", "next_retry_at", "fail_count"} <= servers
        assert "annotations" in tools
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_sync)            # a second run changes nothing
        assert await _snapshot(engine) == first
    finally:
        await engine.dispose()


async def test_0068_leaves_a_database_without_the_tables_alone(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_sync)
            names = {r[0] for r in (await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'")).all()}
        assert names == set()
    finally:
        await engine.dispose()
