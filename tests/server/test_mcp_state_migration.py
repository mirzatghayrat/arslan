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
# (id, status, host_allowed): connected, error, the user's real rea row, then three switched-off
# ones (connected / error / registered): host access off wins over whatever status they last had.
_ROWS = ((1, "connected", 1), (2, "error", 1), (3, "disconnected", 1), (4, "connected", 0),
         (5, "error", 0), (6, "registered", 0))


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
        assert {r[0]: r[1] for r in rows} == {
            1: "ready", 2: "failed", 3: "starting", 4: "off", 5: "off", 6: "off"}
        assert all(r[2] == 0 and r[3] is None and r[4] is None and r[5] is None for r in rows)
        assert {"state", "state_at", "last_ok_at", "next_retry_at", "fail_count"} <= servers
        assert "annotations" in tools
        async with engine.begin() as conn:
            await conn.run_sync(upgrade_sync)            # a second run changes nothing
        assert await _snapshot(engine) == first
        # What the supervisor writes later must survive a re-run: the legacy-status backfill
        # happens once, when `state` is created, and never again.
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "UPDATE mcp_servers SET state = 'parked', fail_count = 3 WHERE id = 1")
            await conn.run_sync(upgrade_sync)
        rows_after, _, _ = await _snapshot(engine)
        assert [r[:3] for r in rows_after if r[0] == 1] == [(1, "parked", 3)]
        # The columns carry their own defaults: a row that names neither gets ('starting', 0).
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO mcp_servers (id, label, command, args) VALUES (9, 'n', 'x', '[]')")
            bare = (await conn.exec_driver_sql(
                "SELECT state, fail_count FROM mcp_servers WHERE id = 9")).one()
        assert tuple(bare) == ("starting", 0)
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
