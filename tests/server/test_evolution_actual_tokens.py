"""`EvolutionAttempt.actual` must record REAL spend — step 1 of the user's ruling
(actual落库 → 修估算器 → 攒真实分布 → 用数据定预算默认值).

WHAT WAS ACTUALLY MISSING. The memory said "zero real spend data in the system"; that is
not quite right. Replay dispatches ALREADY land fully accounted on `Run` rows
(kind='replay', task_tokens, tokens_in/out, tokens_estimated) and the usage card already
counts them. What was lost is the judge / optimizer / synthetic-generation calls:
`propose_improvement` never opens `usage_sink.collecting()` and runs in a bare
create_task, so every `usage_sink.report()` on those paths is a silent no-op. Judge calls
dominate the estimate's arithmetic, so the majority of non-dispatch spend was invisible.

TWO PROPERTIES THIS FILE EXISTS TO PIN, both from the user's rulings:

  ① SAME BASIS. estimate.est_tokens = avg_run*dispatches + AVG_JUDGE*judge_calls — it is
     DOMINATED by the dispatch term. An `actual.est_tokens` holding only the non-dispatch
     tokens would render, side by side on the promotion card, as roughly an order of
     magnitude cheaper for reasons that have nothing to do with reality. So actual
     includes dispatch tokens too, and the split is reported so nobody has to guess.

  ② ATTRIBUTION BY IDENTITY, NOT BY TIME. Dispatch tokens are summed over the run_ids
     THIS attempt caused, collected through a task-local contextvar. A
     (spawn_id, time-window) join would silently absorb skill_forge's replays, which use
     the same spawn_id AND the same sentinel conversation_id and are not covered by the
     watcher's concurrency guard.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from arslan.llm import usage_sink
from server.db.models import EvolutionAttempt, Run
from server.services import (
    evolution_loop,
    evolution_meter,
    evolution_watcher,
    replay_run,
)

from .test_evolution_watcher import _drain, _spawn  # noqa: F401


async def _seed_replay_run(Session, spawn_id: int, tokens: int, *, estimated=False) -> int:
    async with Session() as db:
        r = Run(conversation_id=replay_run.REPLAY_CONVERSATION_ID, spawn_id=spawn_id,
                user_message="t", task_tokens=tokens, status="replayed", kind="replay",
                epoch=1, tokens_estimated=estimated)
        db.add(r)
        await db.commit()
        await db.refresh(r)
        return r.id


# ── the collector itself ───────────────────────────────────────────────────────────


async def test_collector_gathers_only_ids_from_inside_its_block():
    with replay_run.collect_run_ids() as ids:
        replay_run._note_run_id(1)
        replay_run._note_run_id(2)
    replay_run._note_run_id(3)          # outside — must not be gathered
    assert ids == [1, 2]


async def test_collector_is_task_local(wdb):
    """🔴 The property that makes identity-attribution safe. skill_forge calls the same
    run_arm for the same spawn with the same sentinel conversation_id and is NOT covered
    by the watcher's per-spawn concurrency guard — so a concurrent one must be unable to
    leak into this attempt's collection. A contextvar is per-TASK, so it cannot."""
    seen: dict[str, list[int]] = {}

    async def evolution_side():
        with replay_run.collect_run_ids() as ids:
            replay_run._note_run_id(10)
            await asyncio.sleep(0)          # let the other task interleave
            replay_run._note_run_id(11)
            seen["evolution"] = list(ids)

    async def skill_forge_side():
        with replay_run.collect_run_ids() as ids:
            replay_run._note_run_id(99)
            await asyncio.sleep(0)
            seen["forge"] = list(ids)

    await asyncio.gather(evolution_side(), skill_forge_side())
    assert seen["evolution"] == [10, 11]
    assert 99 not in seen["evolution"], "another task's replay leaked into the attempt"


async def test_noting_outside_a_collection_is_a_no_op():
    """run_arm always notes; with no collection active that must be free and harmless."""
    replay_run._note_run_id(42)          # must not raise


# ── what lands in `actual` ─────────────────────────────────────────────────────────


@pytest.fixture
def spend(monkeypatch):
    """Stub propose_improvement so it reports a known amount of DIRECT (judge/optimizer)
    spend and claims a known set of replay run_ids, without any LLM or dispatch."""
    def _make(*, direct_tokens: int, run_ids: list[int], counters: dict):
        async def fake_propose(spawn_id, **k):
            usage_sink.report(direct_tokens)
            for rid in run_ids:
                replay_run._note_run_id(rid)
            # counters come from the task-local meter, bumped where the calls really
            # happen — NOT from the return value, because three of
            # propose_improvement's six returns are early exits and those are exactly
            # the attempts whose cost most needs to be recorded.
            for key, n in counters.items():
                if key != "dispatches":      # dispatches is counted from run_ids
                    evolution_meter.bump(key, n)
            return {"proposal_id": None, "candidate_prompt": "C",
                    "gate": {"passed": False, "reason": "holdout_winrate", "aggregate": None},
                    "evidence": {}}
        monkeypatch.setattr(evolution_loop, "propose_improvement", fake_propose)
    return _make


async def test_actual_is_recorded_at_all(wdb, spend):
    Session = wdb
    sid = await _spawn(Session)
    rid = await _seed_replay_run(Session, sid, 500)
    spend(direct_tokens=1200, run_ids=[rid],
          counters={"pairs": 4, "dispatches": 1, "judge_calls": 2,
                    "optimizer_calls": 3, "synth_calls": 0})

    await evolution_watcher.enqueue_attempt(sid, manual=False)
    await _drain()

    async with Session() as db:
        att = (await db.execute(select(EvolutionAttempt))).scalars().one()
    assert att.actual is not None, "actual must no longer be permanently NULL"


async def test_actual_uses_the_SAME_BASIS_as_the_estimate(wdb, spend):
    """🔴 Ruling ①. estimate.est_tokens is dominated by the dispatch term, so an actual
    that omitted dispatch tokens would look ~10x cheaper for reasons unrelated to
    reality — and PromotionCard renders the two under the same key name."""
    Session = wdb
    sid = await _spawn(Session)
    a = await _seed_replay_run(Session, sid, 500)
    b = await _seed_replay_run(Session, sid, 700)
    spend(direct_tokens=1200, run_ids=[a, b],
          counters={"pairs": 4, "dispatches": 2, "judge_calls": 2,
                    "optimizer_calls": 3, "synth_calls": 0})

    await evolution_watcher.enqueue_attempt(sid, manual=False)
    await _drain()

    async with Session() as db:
        att = (await db.execute(select(EvolutionAttempt))).scalars().one()
    assert att.actual["dispatch_tokens"] == 1200        # 500 + 700, from the Run rows
    assert att.actual["direct_tokens"] == 1200          # judge/optimizer, from the sink
    assert att.actual["est_tokens"] == 2400, (
        "est_tokens must be the TOTAL, matching what the estimate's est_tokens means")


async def test_a_concurrent_skill_forge_replay_does_not_enter_this_actual(wdb, spend):
    """🔴 Ruling ②. skill_forge replays carry the same spawn_id and the same sentinel
    conversation_id, and are not covered by _running_spawns. A (spawn_id, time-window)
    join would absorb them; identity attribution cannot."""
    Session = wdb
    sid = await _spawn(Session)
    mine = await _seed_replay_run(Session, sid, 500)
    await _seed_replay_run(Session, sid, 9999)          # skill_forge's — same spawn, same window
    spend(direct_tokens=0, run_ids=[mine],
          counters={"pairs": 1, "dispatches": 1, "judge_calls": 0,
                    "optimizer_calls": 1, "synth_calls": 0})

    await evolution_watcher.enqueue_attempt(sid, manual=False)
    await _drain()

    async with Session() as db:
        att = (await db.execute(select(EvolutionAttempt))).scalars().one()
    assert att.actual["dispatch_tokens"] == 500, (
        "another caller's replay was absorbed — attribution must be by run_id, not by "
        "spawn_id and a time window")


async def test_actual_says_when_its_numbers_are_adapter_ESTIMATES(wdb, spend):
    """🔴 A replay Run's task_tokens is itself an adapter estimate whenever the provider
    returned no usage (a CJK-aware character heuristic). Calling that "actual" without
    saying so is the same overclaim this work item exists to end."""
    Session = wdb
    sid = await _spawn(Session)
    good = await _seed_replay_run(Session, sid, 500, estimated=False)
    guess = await _seed_replay_run(Session, sid, 300, estimated=True)
    spend(direct_tokens=0, run_ids=[good, guess],
          counters={"pairs": 2, "dispatches": 2, "judge_calls": 0,
                    "optimizer_calls": 1, "synth_calls": 0})

    await evolution_watcher.enqueue_attempt(sid, manual=False)
    await _drain()

    async with Session() as db:
        att = (await db.execute(select(EvolutionAttempt))).scalars().one()
    assert att.actual["estimated"] is True, (
        "one component was a heuristic — the payload must admit it")


async def test_actual_carries_the_real_counters_not_the_projected_ones(wdb, spend):
    Session = wdb
    sid = await _spawn(Session)
    rid = await _seed_replay_run(Session, sid, 100)
    spend(direct_tokens=10, run_ids=[rid],
          counters={"pairs": 7, "dispatches": 1, "judge_calls": 5,
                    "optimizer_calls": 2, "synth_calls": 3})

    await evolution_watcher.enqueue_attempt(sid, manual=False)
    await _drain()

    async with Session() as db:
        att = (await db.execute(select(EvolutionAttempt))).scalars().one()
    for k, v in [("pairs", 7), ("judge_calls", 5), ("optimizer_calls", 2), ("synth_calls", 3)]:
        assert att.actual[k] == v, f"{k}: {att.actual[k]} != {v}"


async def test_spend_on_a_FAILED_attempt_is_still_recorded(wdb, monkeypatch):
    """Tokens burned on a failing run are still tokens burned — and a failed attempt is
    exactly the one whose cost most needs to be visible."""
    Session = wdb
    sid = await _spawn(Session)
    rid = await _seed_replay_run(Session, sid, 400)

    async def boom(spawn_id, **k):
        usage_sink.report(800)
        replay_run._note_run_id(rid)
        raise RuntimeError("adapter down")

    monkeypatch.setattr(evolution_loop, "propose_improvement", boom)
    await evolution_watcher.enqueue_attempt(sid, manual=False)
    await _drain()

    async with Session() as db:
        att = (await db.execute(select(EvolutionAttempt))).scalars().one()
    assert att.outcome == "error"
    assert att.actual is not None and att.actual["est_tokens"] == 1200
