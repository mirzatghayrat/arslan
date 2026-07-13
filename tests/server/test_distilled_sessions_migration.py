"""The _0013 migration's upgrade_sync must build a working distilled_sessions schema.

Unlike test_distilled_session_model.py (which exercises Base.metadata.create_all),
this proves the migration path itself — the code wired into server/main.py boot —
produces the table AND its uq_distilled_conv_spawn unique constraint end-to-end,
without relying on create_all.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import DistilledSession


async def test_migration_creates_table_and_unique_constraint(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'d.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Table is created by the migration's upgrade_sync, NOT create_all.
    async with engine.begin() as conn:
        from server.db.migrations.versions._0013_distilled_sessions import upgrade_sync
        await conn.run_sync(upgrade_sync)
        # Idempotent: a second run on an existing table must no-op, not raise.
        await conn.run_sync(upgrade_sync)

    async with maker() as s:
        s.add(DistilledSession(conversation_id="c1", spawn_id=3))
        await s.commit()

    # The (conversation_id, spawn_id) marker must round-trip.
    async with maker() as s:
        rows = (await s.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == "c1",
            DistilledSession.spawn_id == 3))).scalars().all()
    assert len(rows) == 1

    # uq_distilled_conv_spawn must reject a duplicate pair (proves the
    # migration created the constraint, not just a bare table).
    with pytest.raises(IntegrityError):
        async with maker() as s:
            s.add(DistilledSession(conversation_id="c1", spawn_id=3))
            await s.commit()
