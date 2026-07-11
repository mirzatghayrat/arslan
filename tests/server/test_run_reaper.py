"""E1: boot reaper re-enqueues judge scoring for stuck runs + manual rescore endpoint.

A run left in 'recorded'/'score_failed' for >10 minutes (process died around
scoring) is re-enqueued at boot; fresh runs and terminal statuses are not.
POST /runs/{id}/rescore re-enqueues one run (404 unknown).
NOTE: once E2 adds runs.kind, the reaper/rescore must also filter kind='live'.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, Run
from server.services import run_reaper, run_recorder


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


def _capture_scheduling(monkeypatch) -> list[int]:
    enqueued: list[int] = []
    monkeypatch.setattr(run_recorder, "schedule_scoring", enqueued.append)
    return enqueued


async def _seed_run(Session, *, status: str, age_minutes: int, kind: str = "live") -> int:
    async with Session() as db:
        run = Run(conversation_id="c1", spawn_name="Mermer", user_message="m",
                  status=status, task_tokens=0, kind=kind,
                  created_at=datetime.utcnow() - timedelta(minutes=age_minutes))
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def test_stuck_recorded_run_is_reenqueued(memdb, monkeypatch):
    enqueued = _capture_scheduling(monkeypatch)
    stuck_id = await _seed_run(memdb, status="recorded", age_minutes=20)
    n = await run_reaper.reap_stuck_runs()
    assert n == 1
    assert enqueued == [stuck_id]


async def test_stuck_score_failed_run_is_reenqueued(memdb, monkeypatch):
    enqueued = _capture_scheduling(monkeypatch)
    stuck_id = await _seed_run(memdb, status="score_failed", age_minutes=11)
    await run_reaper.reap_stuck_runs()
    assert enqueued == [stuck_id]


async def test_fresh_run_is_not_reenqueued(memdb, monkeypatch):
    enqueued = _capture_scheduling(monkeypatch)
    await _seed_run(memdb, status="recorded", age_minutes=0)
    n = await run_reaper.reap_stuck_runs()
    assert n == 0
    assert enqueued == []


async def test_terminal_statuses_are_not_reenqueued(memdb, monkeypatch):
    enqueued = _capture_scheduling(monkeypatch)
    await _seed_run(memdb, status="scored", age_minutes=60)
    await _seed_run(memdb, status="recording", age_minutes=60)
    # E1 forward-guard: replay runs (E3) get terminal status 'replayed' and must
    # NEVER match any scoring machinery.
    await _seed_run(memdb, status="replayed", age_minutes=60)
    await run_reaper.reap_stuck_runs()
    assert enqueued == []


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


# --- POST /runs/{id}/rescore -------------------------------------------------

async def test_rescore_404_on_unknown_run(client):
    resp = await client.post("/api/v1/runs/999999/rescore")
    assert resp.status_code == 404


async def _seed_run_via_client(client, *, status: str) -> int:
    async with client.db_maker() as db:
        run = Run(conversation_id="c1", spawn_name="Mermer", user_message="m",
                  status=status, task_tokens=0)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def test_rescore_enqueues_known_run(client, monkeypatch):
    enqueued = _capture_scheduling(monkeypatch)
    run_id = await _seed_run_via_client(client, status="score_failed")
    resp = await client.post(f"/api/v1/runs/{run_id}/rescore")
    assert resp.status_code == 200
    assert resp.json() == {"enqueued": True}
    assert enqueued == [run_id]


async def test_rescore_scored_run_still_accepted(client, monkeypatch):
    """Regression for the S3-M1 terminal-status guard: 'scored' stays rescorable."""
    enqueued = _capture_scheduling(monkeypatch)
    run_id = await _seed_run_via_client(client, status="scored")
    resp = await client.post(f"/api/v1/runs/{run_id}/rescore")
    assert resp.status_code == 200
    assert enqueued == [run_id]


@pytest.mark.parametrize("status", ["cancelled", "interrupted"])
async def test_rescore_terminal_unscored_run_409s(client, monkeypatch, status):
    """S3-M1 invariant: cancelled/interrupted runs are never scored and never
    corpus-eligible — rescoring one would judge partial output and flip it to
    'scored', so the endpoint must refuse."""
    enqueued = _capture_scheduling(monkeypatch)
    run_id = await _seed_run_via_client(client, status=status)
    resp = await client.post(f"/api/v1/runs/{run_id}/rescore")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "not rescorable" in detail
    assert status in detail
    assert enqueued == []
