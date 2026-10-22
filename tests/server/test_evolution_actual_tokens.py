"""Replay run-id collection and dispatch accounting (evolution_meter / replay_run).

These pinned how an evolution attempt's REAL spend was attributed: dispatch tokens are
summed over the run_ids the attempt itself caused (a task-local collector), never by a
(spawn_id, time-window) join that would absorb a concurrent replay. The attempt-level
`actual` tests went with the manual evolve path (C7b-1); what is left still exercises live
code and goes with replay_run / evolution_meter in C7 step 2's replay and dispatcher PRs.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from arslan.llm import usage_sink
from server.db.models import Run, Spawn
from server.services import evolution_meter, replay_run


async def _spawn(Session) -> int:
    async with Session() as db:
        s = Spawn(name="S", domain_category="x", system_prompt="P", generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


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


# ── the REAL dispatch path ─────────────────────────────────────────────────────────
#
# 🔴 Every test above stubs propose_improvement, so none of them touches run_arm, the
# dispatcher, or the nested collecting() the design rests on. That gap is exactly where
# the BLOCKER lived: a dispatch that RAISES had already persisted its tokens on the Run
# row, and the id was noted only after dispatch RETURNED — so the spend was burned,
# durable, and counted by nothing, while `actual` still said estimated: False.


async def test_a_dispatch_that_RAISES_is_still_counted(wdb, monkeypatch):
    """Drive the real replay_run -> dispatcher path with a model that dies mid-run."""
    from server.orchestrator import dispatcher

    Session = wdb
    sid = await _spawn(Session)

    async def dying_model(*a, **k):
        usage_sink.report(4242)          # tokens really burned before the failure
        raise RuntimeError("provider 500")

    monkeypatch.setattr(dispatcher, "_run_model", dying_model)

    with evolution_meter.counting(), evolution_meter.collect_run_ids() as ids:
        with pytest.raises(RuntimeError):
            async with Session() as db:
                await replay_run.run_arm(
                    db, spawn_id=sid, task="t", system_prompt="p",
                    # the real shape snapshot_ambient returns — a bare {} trips a
                    # KeyError deep in the dispatcher long before the path under test
                    ambient={"facts": "", "kb_block": "", "kb_sources": []})
        assert ids, "the failed dispatch's run_id was not collected — its tokens are lost"
        assert evolution_meter.snapshot().get("failed_dispatches") == 1

    async with Session() as db:
        row = (await db.execute(select(Run).where(Run.id == ids[0]))).scalars().one()
    assert row.task_tokens == 4242, "the Run row holds the burned tokens"
