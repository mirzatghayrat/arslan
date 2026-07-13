"""Background evolution watcher — trigger, deterministic backoff, budget, concurrency
(S2 E5, audit CRITICAL-4).

C4 is the regression the USER will personally verify: a FAILED attempt is recorded AND the
same runs do not re-trigger every tick — the threshold backs off and the runs are now behind
the attempt, so there is no unbounded 5-minute retry loop.

Everything is stubbed at the propose/estimate seam so the tests exercise the WATCHER's
trigger + attempt bookkeeping deterministically, never a real LLM or a real gate.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, EvolutionAttempt, Run, Setting, Spawn
from server.services import evolution_estimate, evolution_loop, evolution_watcher


@pytest.fixture
async def wdb(tmp_path, monkeypatch):
    """A file-backed SQLite DB wired into db_session.AsyncSessionLocal (so the watcher's own
    sessions hit it), with a cheap stubbed estimate. Resets watcher module state around each
    test so nothing bleeds."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'w.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)

    async def fake_estimate(db, spawn_id):
        return {"pairs": 4, "dispatches": 56, "judge_calls": 56, "optimizer_calls": 3,
                "synth_calls": 0, "est_tokens": 1000, "lower_bound": True}

    monkeypatch.setattr(evolution_estimate, "estimate", fake_estimate)

    evolution_watcher._running_spawns.clear()
    yield Session
    for t in list(evolution_watcher._tasks):
        t.cancel()
    evolution_watcher._tasks.clear()
    evolution_watcher._running_spawns.clear()
    await engine.dispose()


async def _fail_propose(spawn_id, **k):
    return {"proposal_id": None, "candidate_prompt": "C",
            "gate": {"passed": False, "reason": "holdout_winrate", "aggregate": None},
            "evidence": {}}


async def _pass_propose(spawn_id, **k):
    return {"proposal_id": 123, "candidate_prompt": "C",
            "gate": {"passed": True, "reason": "pass", "aggregate": {}}, "evidence": {}}


async def _spawn(Session) -> int:
    async with Session() as db:
        s = Spawn(name="S", domain_category="x", system_prompt="P", generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def _seed_runs(Session, spawn_id, n, *, created_at=None, tag="") -> None:
    async with Session() as db:
        for i in range(n):
            db.add(Run(
                conversation_id="c", spawn_id=spawn_id,
                user_message=f"task-{spawn_id}-{tag}-{i}", task_tokens=100,
                status="scored", kind="live", epoch=1,
                created_at=created_at or datetime.utcnow(),
            ))
        await db.commit()


async def _attempts(Session, spawn_id) -> list[EvolutionAttempt]:
    async with Session() as db:
        return (await db.execute(
            select(EvolutionAttempt).where(EvolutionAttempt.spawn_id == spawn_id)
            .order_by(EvolutionAttempt.id)
        )).scalars().all()


async def _drain() -> None:
    """Await every supervised runner task the trigger just launched."""
    for _ in range(50):
        tasks = [t for t in evolution_watcher._tasks if not t.done()]
        if not tasks:
            break
        await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0)


# ── backoff schedule (pure) ────────────────────────────────────────────────────────────

def test_backoff_schedule():
    t = evolution_watcher._threshold
    # 10 → 20 → 40 → 80, then capped at 80 (base * MAX_BACKOFF_MULT).
    assert [t(0), t(1), t(2), t(3), t(4), t(5)] == [10, 20, 40, 80, 80, 80]


# ── CRITICAL C4 ─────────────────────────────────────────────────────────────────────────

async def test_C4_failed_attempt_backs_off_and_records(wdb, monkeypatch):
    Session = wdb
    monkeypatch.setattr(evolution_loop, "propose_improvement", _fail_propose)

    sid = await _spawn(Session)
    past = datetime.utcnow() - timedelta(hours=1)
    await _seed_runs(Session, sid, 10, created_at=past, tag="a")

    # Tick 1: 10 new runs (no prior attempt) ≥ threshold 10 → an attempt fires and FAILS.
    aid = await evolution_watcher.trigger_spawn(sid)
    assert aid is not None
    await _drain()

    attempts = await _attempts(Session, sid)
    assert len(attempts) == 1
    assert attempts[0].outcome == "failed"          # gate failed → durable 'failed' record
    assert attempts[0].finished_at is not None
    assert attempts[0].reason == "holdout_winrate"
    t1 = attempts[0].started_at

    # Tick 2: the SAME 10 runs are now BEHIND the attempt (0 new since t1) AND the threshold
    # doubled to 20 → NOT eligible. This is the anti-runaway property: no re-trigger.
    assert await evolution_watcher.trigger_spawn(sid) is None
    async with Session() as db:
        n = (await db.execute(select(func.count()).select_from(EvolutionAttempt)
                              .where(EvolutionAttempt.spawn_id == sid))).scalar()
    assert n == 1   # still exactly one attempt — no unbounded 5-min retry loop

    # 19 fresh runs after the attempt: still one short of the backed-off threshold of 20.
    await _seed_runs(Session, sid, 19, created_at=t1 + timedelta(seconds=5), tag="b")
    assert await evolution_watcher.trigger_spawn(sid) is None

    # The 20th fresh run tips it over the doubled threshold → a SECOND attempt requires 20.
    await _seed_runs(Session, sid, 1, created_at=t1 + timedelta(seconds=6), tag="c")
    aid2 = await evolution_watcher.trigger_spawn(sid)
    assert aid2 is not None
    await _drain()

    attempts = await _attempts(Session, sid)
    assert len(attempts) == 2
    assert [a.outcome for a in attempts] == ["failed", "failed"]


# ── E9-b (a): structural-fail transparency ───────────────────────────────────────────────

async def _structural_propose(spawn_id, **k):
    return {"proposal_id": None, "candidate_prompt": "C",
            "gate": {"passed": False, "reason": "length_cap", "aggregate": None},
            "evidence": {}}


async def test_structural_fail_is_skipped_structural_and_does_not_back_off(wdb, monkeypatch):
    """A pre-run STRUCTURAL failure (length_cap) is recorded outcome='skipped_structural' and is
    transparent to the backoff streak — a lone structural skip leaves the streak at 0 (threshold
    stays the BASE 10). It says nothing about the spawn's prompt, so it must not punish it."""
    Session = wdb
    monkeypatch.setattr(evolution_loop, "propose_improvement", _structural_propose)
    sid = await _spawn(Session)

    aid = await evolution_watcher.enqueue_attempt(sid, manual=True)
    assert aid is not None
    await _drain()

    async with Session() as db:
        att = await db.get(EvolutionAttempt, aid)
        assert att.outcome == "skipped_structural"
        assert att.reason == "length_cap"
        # backoff is unaffected — a lone structural skip leaves the streak at 0 (threshold 10).
        assert await evolution_watcher._consecutive_fails(db, sid) == 0
        assert evolution_watcher._threshold(
            await evolution_watcher._consecutive_fails(db, sid)) == evolution_watcher.BASE_THRESHOLD


async def test_consecutive_fails_sees_through_structural_skips(wdb):
    """Transparency: two genuine quality fails on either side of a structural skip still both
    count (streak 2) — the skip is neither counted nor a wall that resets the streak."""
    Session = wdb
    sid = await _spawn(Session)
    async with Session() as db:
        # oldest → newest (by insertion / id): failed, skipped_structural, failed.
        db.add_all([
            EvolutionAttempt(spawn_id=sid, outcome="failed", reason="holdout_winrate",
                             started_at=datetime(2026, 7, 1)),
            EvolutionAttempt(spawn_id=sid, outcome="skipped_structural", reason="length_cap",
                             started_at=datetime(2026, 7, 2)),
            EvolutionAttempt(spawn_id=sid, outcome="failed", reason="holdout_winrate",
                             started_at=datetime(2026, 7, 3)),
        ])
        await db.commit()
    async with Session() as db:
        # both genuine fails count; the structural skip is transparent (not counted, not a wall).
        assert await evolution_watcher._consecutive_fails(db, sid) == 2


async def test_consecutive_fails_sees_through_error_attempts(wdb):
    """An 'error' outcome (an infra/adapter failure surfaced by the loop, or a crash) is
    TRANSPARENT to the QUALITY backoff — like a structural skip it neither counts toward the
    streak nor resets it. A dead judge adapter must not inflate the run-count threshold as if
    the spawn's prompt were un-improvable."""
    Session = wdb
    sid = await _spawn(Session)
    async with Session() as db:
        # oldest → newest: failed, error, failed.
        db.add_all([
            EvolutionAttempt(spawn_id=sid, outcome="failed", reason="holdout_winrate",
                             started_at=datetime(2026, 7, 1)),
            EvolutionAttempt(spawn_id=sid, outcome="error", reason="RuntimeError: llm down",
                             started_at=datetime(2026, 7, 2)),
            EvolutionAttempt(spawn_id=sid, outcome="failed", reason="holdout_winrate",
                             started_at=datetime(2026, 7, 3)),
        ])
        await db.commit()
    async with Session() as db:
        # both genuine fails count; the infra 'error' is transparent (not counted, not a wall).
        assert await evolution_watcher._consecutive_fails(db, sid) == 2


def test_is_structural_covers_all_three_construction_reasons():
    """The three CONSTRUCTION/precondition reasons are structural (transparent to backoff);
    genuine QUALITY reasons are not (they still escalate the streak). 'insufficient scored runs'
    was user-confirmed 2026-07-13 as the same class as insufficient_holdout."""
    for reason in ("length_cap", "insufficient_holdout", "insufficient scored runs"):
        assert evolution_watcher._is_structural(reason) is True
    for reason in ("holdout_winrate", "real_floor", "verbose_fail",
                   "dim_regressed:fabrication", "no accepted edit beats the original"):
        assert evolution_watcher._is_structural(reason) is False


# ── evolution_auto gate ─────────────────────────────────────────────────────────────────

async def test_evolution_auto_off_never_runs(wdb, monkeypatch):
    Session = wdb
    monkeypatch.setattr(evolution_loop, "propose_improvement", _fail_propose)
    sid = await _spawn(Session)
    await _seed_runs(Session, sid, 10)
    async with Session() as db:
        db.add(Setting(key="evolution_auto", value="off"))
        await db.commit()

    assert await evolution_watcher.trigger_spawn(sid) is None
    await _drain()
    assert await _attempts(Session, sid) == []


# ── budget cap ──────────────────────────────────────────────────────────────────────────

async def test_over_budget_records_skipped_budget(wdb, monkeypatch):
    Session = wdb
    called = {"propose": False}

    async def spy_propose(spawn_id, **k):
        called["propose"] = True
        return await _fail_propose(spawn_id, **k)

    monkeypatch.setattr(evolution_loop, "propose_improvement", spy_propose)
    sid = await _spawn(Session)
    await _seed_runs(Session, sid, 10)
    async with Session() as db:   # estimate est_tokens=1000 (fixture) > 500 budget
        db.add(Setting(key="evolution_max_est_tokens", value="500"))
        await db.commit()

    aid = await evolution_watcher.trigger_spawn(sid)
    assert aid is not None        # an attempt row IS created (honest record of the skip)
    await _drain()

    attempts = await _attempts(Session, sid)
    assert len(attempts) == 1
    assert attempts[0].outcome == "skipped_budget"
    assert called["propose"] is False   # propose_improvement was NOT run


# ── passed attempt resets backoff ───────────────────────────────────────────────────────

async def test_passed_attempt_resets_threshold(wdb, monkeypatch):
    Session = wdb
    monkeypatch.setattr(evolution_loop, "propose_improvement", _pass_propose)
    sid = await _spawn(Session)
    past = datetime.utcnow() - timedelta(hours=1)
    await _seed_runs(Session, sid, 10, created_at=past, tag="a")

    aid = await evolution_watcher.trigger_spawn(sid)
    assert aid is not None
    await _drain()

    attempts = await _attempts(Session, sid)
    assert len(attempts) == 1
    assert attempts[0].outcome == "passed"
    assert attempts[0].proposal_id == 123
    t1 = attempts[0].started_at

    # After a PASS the streak is 0 → threshold is back to the base 10, so 10 fresh runs
    # (NOT 20) are enough to be eligible again.
    await _seed_runs(Session, sid, 10, created_at=t1 + timedelta(seconds=5), tag="b")
    async with Session() as db:
        assert await evolution_watcher._consecutive_fails(db, sid) == 0
        assert evolution_watcher._threshold(0) == 10
        assert await evolution_watcher._is_eligible(db, sid) is True


# ── concurrency = 1 per spawn ───────────────────────────────────────────────────────────

async def test_concurrency_one_per_spawn(wdb, monkeypatch):
    Session = wdb
    monkeypatch.setattr(evolution_loop, "propose_improvement", _fail_propose)
    sid = await _spawn(Session)
    await _seed_runs(Session, sid, 10)

    # Mark the spawn as already running → a second trigger must not enqueue anything.
    evolution_watcher._running_spawns.add(sid)
    assert await evolution_watcher.trigger_spawn(sid) is None
    evolution_watcher._running_spawns.discard(sid)
    await _drain()
    assert await _attempts(Session, sid) == []
