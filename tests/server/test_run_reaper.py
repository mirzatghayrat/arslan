"""S3-M1 boot sweep: orphaned 'recording' runs become 'interrupted'.

C7c-5a removed the judge re-enqueue (reap_stuck_runs) and POST /runs/{id}/rescore with the
scoring path: nothing scores runs any more. Their tests went; the two below check they are gone.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, Run
from server.services import run_reaper


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _seed_run(Session, *, status: str, age_minutes: int, kind: str = "live") -> int:
    async with Session() as db:
        run = Run(conversation_id="c1", spawn_name="Mermer", user_message="m",
                  status=status, task_tokens=0, kind=kind,
                  created_at=datetime.utcnow() - timedelta(minutes=age_minutes))
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


def test_the_judge_reenqueue_is_gone():
    assert not hasattr(run_reaper, "reap_stuck_runs")
    assert not hasattr(run_reaper, "_reaper_candidates")


# --- S3-M1 boot sweep: orphaned 'recording' rows → 'interrupted' -------------

async def test_mark_interrupted_sweeps_orphaned_recording_rows(memdb):
    orphan_id = await _seed_run(memdb, status="recording", age_minutes=5)
    recorded_id = await _seed_run(memdb, status="recorded", age_minutes=5)
    replay_id = await _seed_run(memdb, status="recording", age_minutes=5, kind="replay")

    n = await run_reaper.mark_interrupted_runs()
    assert n == 1

    async with memdb() as db:
        orphan = await db.get(Run, orphan_id)
        recorded = await db.get(Run, recorded_id)
        replay = await db.get(Run, replay_id)
    assert orphan.status == "interrupted"
    assert orphan.ended_at is not None
    assert recorded.status == "recorded"
    assert replay.status == "recording"


# --- S3-M4: old scheduled runs share the sweep (replay stays out) ----------------

async def test_scheduled_runs_are_swept_like_live(memdb):
    """An old kind='scheduled' row is swept like a live one: a crashed 'recording' row →
    'interrupted'. A 'recorded' one is left as it is (nothing re-enqueues scoring now)."""
    orphan_id = await _seed_run(memdb, status="recording", age_minutes=5,
                                kind="scheduled")
    stuck_id = await _seed_run(memdb, status="recorded", age_minutes=20,
                               kind="scheduled")

    assert await run_reaper.mark_interrupted_runs() == 1
    async with memdb() as db:
        orphan = await db.get(Run, orphan_id)
        stuck = await db.get(Run, stuck_id)
    assert orphan.status == "interrupted"
    assert stuck.status == "recorded"


# --- POST /runs/{id}/rescore: gone ---------------------------------------------

async def test_the_rescore_route_is_gone(client):
    async with client.db_maker() as db:
        run = Run(conversation_id="c1", spawn_name="Mermer", user_message="m",
                  status="score_failed", task_tokens=0, kind="live")
        db.add(run)
        await db.commit()
        await db.refresh(run)
    assert (await client.get(f"/api/v1/runs/{run.id}")).status_code == 200  # positive control
    assert (await client.post(f"/api/v1/runs/{run.id}/rescore")).status_code in (404, 405)
