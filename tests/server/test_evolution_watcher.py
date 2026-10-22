"""Background evolution watcher — trigger, deterministic backoff, budget, concurrency
(S2 E5, audit CRITICAL-4).

C4 is the regression the USER will personally verify: a FAILED attempt is recorded AND the
same runs do not re-trigger every tick — the threshold backs off and the runs are now behind
the attempt, so there is no unbounded 5-minute retry loop.

Everything is stubbed at the propose/estimate seam so the tests exercise the WATCHER's
trigger + attempt bookkeeping deterministically, never a real LLM or a real gate.

The `wdb` fixture lives in conftest.py, not here: two test modules need it, and importing
a fixture into a second module makes every test that takes it as a parameter look like a
redefinition (ruff F811). conftest is the mechanism pytest provides for exactly this.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select

from server.db.models import EvolutionAttempt, Run, Setting, Spawn
from server.services import evolution_loop, evolution_watcher


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

    # 0036: enqueue as AUTO. These two tests assert that the outcome is TRANSPARENT to the
    # backoff streak; a manual row is a neutral WALL that stops the scan, so enqueueing
    # manually would make `_consecutive_fails == 0` pass for the wrong reason and stop
    # testing transparency at all. (Caught by plan review before it shipped.)
    aid = await evolution_watcher.enqueue_attempt(sid, manual=False)
    assert aid is not None
    await _drain()

    async with Session() as db:
        att = await db.get(EvolutionAttempt, aid)
        assert att.source == "auto"
        assert att.outcome == "skipped_structural"
        assert att.reason == "length_cap"
        # backoff is unaffected — a lone structural skip leaves the streak at 0 (threshold 10).
        assert await evolution_watcher._consecutive_fails(db, sid) == 0
        assert evolution_watcher._threshold(
            await evolution_watcher._consecutive_fails(db, sid)) == evolution_watcher.BASE_THRESHOLD


async def _raising_propose(spawn_id, **k):
    raise RuntimeError("judgment adapter down: 401 Unauthorized")


async def test_infra_error_recorded_as_error_not_failed_and_transparent(wdb, monkeypatch):
    """The honesty-critical link: when propose_improvement RAISES (a dead judge/optimizer adapter),
    _perform_attempt records outcome='error' with the real reason — NOT a quality 'failed' — and
    that error is transparent to the backoff (a lone error leaves the streak at 0, threshold BASE).
    This is the E9-b dead-adapter fix: an infra failure is never masked as a quality verdict."""
    Session = wdb
    monkeypatch.setattr(evolution_loop, "propose_improvement", _raising_propose)
    sid = await _spawn(Session)

    # 0036: enqueue as AUTO. These two tests assert that the outcome is TRANSPARENT to the
    # backoff streak; a manual row is a neutral WALL that stops the scan, so enqueueing
    # manually would make `_consecutive_fails == 0` pass for the wrong reason and stop
    # testing transparency at all. (Caught by plan review before it shipped.)
    aid = await evolution_watcher.enqueue_attempt(sid, manual=False)
    assert aid is not None
    await _drain()

    async with Session() as db:
        att = await db.get(EvolutionAttempt, aid)
        assert att.source == "auto"
        assert att.outcome == "error"                          # infra failure, not quality 'failed'
        assert "judgment adapter down" in (att.reason or "")   # the real exception surfaced
        assert att.finished_at is not None                     # finalized, not left in-flight
        # transparent to the quality backoff — a lone error leaves the streak at 0 (threshold BASE).
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
        # dispatch units now, not tokens
        db.add(Setting(key="evolution_max_dispatches", value="1"))
        await db.commit()

    # 0.1.63 (C1): the automatic trigger always returns None now (C2b deletes it); the
    # budget cap is still enforced on the one live entry, the manual Evolve button.
    aid = await evolution_watcher.enqueue_attempt(sid, manual=True)
    assert aid is not None        # an attempt row IS created (honest record of the skip)
    await _drain()

    attempts = await _attempts(Session, sid)
    assert len(attempts) == 1
    assert attempts[0].outcome == "skipped_budget"
    assert called["propose"] is False   # propose_improvement was NOT run


# ── concurrency = 1 per spawn ───────────────────────────────────────────────────────────

async def test_concurrency_one_per_spawn(wdb, monkeypatch):
    # 0.1.63 (C1): rewritten from the automatic trigger (always None now, C2b deletes it)
    # to the manual entry, which is where the concurrency check lives.
    Session = wdb
    monkeypatch.setattr(evolution_loop, "propose_improvement", _fail_propose)
    sid = await _spawn(Session)
    await _seed_runs(Session, sid, 10)

    # Mark the spawn as already running → a second attempt must not enqueue anything.
    evolution_watcher._running_spawns.add(sid)
    assert await evolution_watcher.enqueue_attempt(sid, manual=True) is None
    evolution_watcher._running_spawns.discard(sid)
    await _drain()
    assert await _attempts(Session, sid) == []

    # The control: with the spawn NOT marked running, the same call DOES enqueue. Without
    # this, "returns None" is satisfied by any reason at all.
    aid = await evolution_watcher.enqueue_attempt(sid, manual=True)
    assert aid is not None, "concurrency test never proved the entry works at all"
    await _drain()
