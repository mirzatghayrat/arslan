"""0036 — the ALTER path, which no generic runner test can reach.

Both runner tests build their DB with Base.metadata.create_all, and models.py already
carries `source` after the sync — so the PRAGMA guard finds the column present and 0036
is a NO-OP in every one of them. The migration would still "pass" if its ALTER were
misspelled. This builds the LEGACY table shape explicitly and drives the real path.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from server.db.migrations.versions._0036_evolution_attempt_source import (
    downgrade_sync,
    upgrade_sync,
)

_LEGACY = """
CREATE TABLE evolution_attempts (
    id INTEGER NOT NULL PRIMARY KEY,
    spawn_id INTEGER NOT NULL,
    started_at DATETIME,
    finished_at DATETIME,
    outcome VARCHAR(20),
    estimate JSON,
    actual JSON,
    proposal_id INTEGER,
    reason TEXT NOT NULL DEFAULT ''
)
"""


def _cols(conn) -> set[str]:
    return {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(evolution_attempts)")}


async def test_alter_adds_the_column_to_a_legacy_table(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(_LEGACY)
        await conn.exec_driver_sql(
            "INSERT INTO evolution_attempts (spawn_id, outcome, reason) "
            "VALUES (1, 'failed', 'holdout_winrate')")
        assert "source" not in await conn.run_sync(_cols)

        await conn.run_sync(upgrade_sync)
        assert "source" in await conn.run_sync(_cols)

        # 🔴 the legacy row must stay NULL — not be backfilled to 'auto', which would
        # fabricate provenance for exactly the manual clicks this column exists to record
        got = (await conn.exec_driver_sql(
            "SELECT source FROM evolution_attempts")).scalar()
        assert got is None
    await engine.dispose()


async def test_reapplying_is_a_no_op(tmp_path):
    """This repo re-applies every migration on EVERY BOOT."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'twice.db'}")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(_LEGACY)
        await conn.run_sync(upgrade_sync)
        await conn.run_sync(upgrade_sync)          # must not raise "duplicate column"
        assert "source" in await conn.run_sync(_cols)
    await engine.dispose()


async def test_a_missing_table_is_skipped_not_crashed(tmp_path):
    """A partial chain / historical fixture can legitimately lack the table; a bare ALTER
    would raise and break the re-apply-every-boot contract."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_sync)          # no table at all — must be a no-op
        await conn.run_sync(downgrade_sync)
    await engine.dispose()


async def test_downgrade_drops_it(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'down.db'}")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(_LEGACY)
        await conn.run_sync(upgrade_sync)
        await conn.run_sync(downgrade_sync)
        assert "source" not in await conn.run_sync(_cols)
    await engine.dispose()
