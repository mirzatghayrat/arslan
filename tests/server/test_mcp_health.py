"""PB-4 MCP equipment health: migration 0027 (the health columns) and the dispatch advisory that
reads them. The on-demand probe (POST /mcp/{id}/health) and the boot sweep were removed in C2e-2:
the supervisor keeps the columns."""

from sqlalchemy.ext.asyncio import create_async_engine


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
