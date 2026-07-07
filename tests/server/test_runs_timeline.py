import datetime as dt

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.api import runs as runs_api
from server.db.models import Base, Run


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'tl.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_timeline_cells_and_severity(maker):
    now = dt.datetime.utcnow()
    async with db_session.AsyncSessionLocal() as db:
        db.add_all([
            Run(conversation_id="c", spawn_id=1, spawn_name="Bad", status="error", error_kind="x",
                total_ms=100, created_at=now - dt.timedelta(minutes=2)),
            Run(conversation_id="c", spawn_id=1, spawn_name="Bad", status="error", error_kind="x",
                total_ms=100, created_at=now - dt.timedelta(minutes=1)),
            Run(conversation_id="c", spawn_id=1, spawn_name="Bad", status="error", error_kind="x",
                total_ms=100, created_at=now - dt.timedelta(seconds=30)),
        ])
        await db.commit()
    async with db_session.AsyncSessionLocal() as db:
        out = await runs_api.runs_timeline(rng="1h", db=db)
    assert len(out.buckets) == 24
    sp = out.spawns[0]
    assert sp.spawn_name == "Bad"
    assert len(sp.cells) == 24
    assert any(c.sev == "red" for c in sp.cells)      # a 100%-error bucket → red
    assert all(c.sev in ("red", "amber", "green", "none") for c in sp.cells)
    # empty buckets are "none"
    assert any(c.sev == "none" and c.count == 0 for c in sp.cells)


@pytest.mark.asyncio
async def test_timeline_empty(maker):
    async with db_session.AsyncSessionLocal() as db:
        out = await runs_api.runs_timeline(rng="1h", db=db)
    assert out.spawns == [] and len(out.buckets) == 24
