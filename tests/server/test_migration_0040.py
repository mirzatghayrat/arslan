"""0040: mcp_servers.host_allowed — server-level host consent (user ruling 2026-08-18).

Backfill semantics matter: existing servers were connected by a human, and
connect IS the consent act under the ruling — so legacy rows get 1, not 0.
"""
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


async def test_migration_0040_adds_column_and_backfills_true(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m40.db'}")
    from server.db.migrations.versions._0040_mcp_host_allowed import upgrade_sync

    async with engine.begin() as conn:
        # A legacy table WITHOUT the column, with one already-connected server.
        await conn.exec_driver_sql(
            "CREATE TABLE mcp_servers (id INTEGER PRIMARY KEY, label VARCHAR(80) NOT NULL, "
            "command VARCHAR(255) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'registered')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO mcp_servers (id, label, command, status) VALUES (1, 'fs', 'npx', 'connected')"
        )
        await conn.run_sync(upgrade_sync)
        await conn.run_sync(upgrade_sync)          # idempotent double-run

    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {x["name"] for x in inspect(c).get_columns("mcp_servers")})
        assert "host_allowed" in cols
        val = (await conn.exec_driver_sql(
            "SELECT host_allowed FROM mcp_servers WHERE id = 1")).scalar()
    assert val == 1                                 # legacy row backfilled to allowed


async def test_migration_0040_noop_without_table(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m40b.db'}")
    from server.db.migrations.versions._0040_mcp_host_allowed import upgrade_sync
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_sync)           # fresh install: create_all owns the schema


async def test_registered_in_runner_chain():
    from server.db.migrations.runner import MIGRATIONS
    assert MIGRATIONS[-1][0] == "0040"              # three-place lockstep: the list is one of them
