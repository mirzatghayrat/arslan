"""Tests for startup backfill wiring (A3b).

Verifies that:
1. upgrade_sync populates a primary provider_configs row from legacy settings keys.
2. server/main.py's lifespan wires the backfill call after create_all.
"""
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from server import crypto
from server.db.models import Base
from server.db.migrations.versions._0006_provider_configs import upgrade_sync


async def test_startup_backfill_populates_primary_from_legacy_key():
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # seed a legacy key the way the running app would have it
        await conn.execute(
            sa.text(
                "INSERT INTO settings (key, value) VALUES "
                "('llm_provider','deepseek'),('llm_model','deepseek-chat'),"
                "('llm_base_url',''),('llm_api_key',:k)"
            ),
            {"k": crypto.encrypt("sk-legacy-99999")},
        )
        await conn.run_sync(upgrade_sync)  # <-- the startup wiring under test
        rows = (
            await conn.execute(
                sa.text("SELECT provider, is_primary, api_key FROM provider_configs")
            )
        ).all()
    await eng.dispose()

    assert len(rows) == 1
    assert rows[0][0] == "deepseek" and rows[0][1] in (1, True)
    assert crypto.decrypt(rows[0][2]) == "sk-legacy-99999"


def test_main_lifespan_calls_backfill():
    """Source-check: main.py wires the versioned migration runner after create_all,
    and the _0006 provider_configs backfill still runs as the runner's first entry.

    (Boot now goes through server.db.migrations.runner.apply_pending instead of the
    old hand-wired per-migration import chain; the backfill behavior is unchanged.)
    """
    import inspect

    import server.main
    from server.db.migrations import runner

    src = inspect.getsource(server.main)
    assert "apply_pending" in src, (
        "server/main.py must call the migration runner's apply_pending after create_all"
    )
    assert "run_sync" in src, (
        "server/main.py must call conn.run_sync(...) to invoke the migrations"
    )
    assert runner.MIGRATIONS[0][0] == "0006", (
        "the _0006 provider_configs backfill must stay first in the runner registry "
        "so it still runs at boot"
    )
