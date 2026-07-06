"""Writes never block on classify; a fire-and-forget classify is scheduled."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'a.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    anyio.run(_seed)
    return m


def test_add_manual_fact_schedules_classify_without_blocking(maker, monkeypatch):
    from server.orchestrator import memory
    from server.services import fact_classify
    scheduled = []
    monkeypatch.setattr(fact_classify, "schedule", lambda coro: (scheduled.append(1), coro.close()))
    row = anyio.run(lambda: memory.add_manual_fact("用户在上海工作"))
    assert row.id is not None            # write completed (returns the row)
    assert scheduled == [1]              # classify was scheduled (not awaited inline)
