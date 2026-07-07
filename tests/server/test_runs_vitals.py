import datetime as dt

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.api import runs as runs_api
from server.db.models import Base, Run


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'v.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_vitals_buckets_and_duration_matrix(maker):
    now = dt.datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        db.add_all([
            Run(conversation_id="c", spawn_id=1, spawn_name="A", status="scored", total_ms=50,
                created_at=now - dt.timedelta(minutes=5)),
            Run(conversation_id="c", spawn_id=1, spawn_name="A", status="error", error_kind="tool", total_ms=4200,
                created_at=now - dt.timedelta(minutes=4)),
            Run(conversation_id="c", spawn_id=1, spawn_name="A", status="scored", total_ms=800,
                created_at=now - dt.timedelta(minutes=1)),
        ])
        await db.commit()
    async with db_session.AsyncSessionLocal() as db:
        out = await runs_api.runs_vitals(rng="1h", db=db)
    assert out.total == 3 and out.error_ratio > 0
    assert len(out.buckets) == 30
    assert sum(b.count for b in out.buckets) == 3
    assert sum(b.errors for b in out.buckets) == 1
    assert len(out.duration_bins) == 6
    assert len(out.duration_matrix) == 6 and len(out.duration_matrix[0]) == 30
    assert sum(sum(row) for row in out.duration_matrix) == 3  # every run placed exactly once


@pytest.mark.asyncio
async def test_vitals_empty(maker):
    async with db_session.AsyncSessionLocal() as db:
        out = await runs_api.runs_vitals(rng="1h", db=db)
    assert out.total == 0 and out.error_ratio == 0.0
    assert len(out.buckets) == 30 and sum(b.count for b in out.buckets) == 0
