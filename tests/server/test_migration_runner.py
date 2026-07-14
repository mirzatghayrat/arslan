"""Tests for the versioned migration runner (server/db/migrations/runner.py)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from server.db.migrations import runner
from server.db.models import Base


async def _fresh(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m.db'}")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return eng


async def test_apply_pending_fills_ledger_and_is_idempotent_at_runner_level(tmp_path):
    eng = await _fresh(tmp_path)
    async with eng.begin() as c:
        applied = await c.run_sync(runner.apply_pending)
    ids = [v for v, _ in runner.MIGRATIONS]
    assert applied == ids                      # applied every registered migration, in order
    async with eng.begin() as c:
        again = await c.run_sync(runner.apply_pending)
    assert again == []                         # second call applies nothing (ledger honored)
    async with eng.connect() as c:
        rows = await c.run_sync(lambda cc: cc.execute(sa.text(
            "SELECT version FROM schema_version ORDER BY version")).scalars().all())
    assert list(rows) == sorted(ids)
