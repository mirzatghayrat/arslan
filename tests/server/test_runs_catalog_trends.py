import datetime as dt

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.api import runs as runs_api
from server.db.models import Base, Run


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'c.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_catalog_has_trend_arrays(maker):
    now = dt.datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        db.add_all([
            Run(conversation_id="c", spawn_id=1, spawn_name="A", status="scored", overall_score=8,
                total_ms=100, created_at=now - dt.timedelta(minutes=30)),
            Run(conversation_id="c", spawn_id=1, spawn_name="A", status="error", error_kind="x",
                total_ms=200, created_at=now - dt.timedelta(minutes=2)),
        ])
        await db.commit()
    async with db_session.AsyncSessionLocal() as db:
        out = await runs_api.runs_catalog(rng="1h", db=db)
    s = out.spawns[0]
    assert len(s.latency_trend) == 12 and len(s.error_trend) == 12 and len(s.rate_trend) == 12
    assert sum(s.rate_trend) == 2
    assert any(e > 0 for e in s.error_trend)
    # score_trend (existing) unaffected
    assert s.score_trend == [8.0]
