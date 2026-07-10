"""FIX 1 (spec §E4 / §2 ruling 3, the methodology crux): the win-rate that CERTIFIES a
proposal is computed on holdout pairs the OPTIMIZER NEVER SAW.

Before the fix, propose_improvement split its train/val by POSITION (replay_set.build_split),
independent of the gate's (spawn_id, task)-hash holdout split — so ~40% of the optimizer's
val tasks were ALSO in the certifying holdout, biasing the "real" win-rate upward. This test
constructs a corpus with a KNOWN propose/holdout partition, records every task the optimizer
touches (edit generation + running-best snapshot + candidate scoring), and asserts that set is
DISJOINT from the holdout tasks that certify the proposal.
"""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, Spawn
from server.services import evaluator, evolution_loop, optimizer, replay_gate, replay_set


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


def _seed_spawn(Session):
    async def _ins():
        async with Session() as db:
            s = Spawn(name="fin", domain_category="x", persona_role="analyst",
                      persona_tone="terse", system_prompt="## Role\nYou are an analyst.",
                      generation_level=1, config={})
            db.add(s)
            await db.commit()
            await db.refresh(s)
            return s.id
    return anyio.run(_ins)


# Known partition: 6 PROPOSE real tasks (the optimizer may see these) + 12 HOLDOUT real tasks
# (the gate certifies on these — the optimizer must never touch them).
_PROPOSE_TASKS = {f"propose-task-{i}" for i in range(6)}
_HOLDOUT_TASKS = {f"holdout-task-{i}" for i in range(12)}


def _corpus():
    c = replay_gate.Corpus()
    for i in range(6):
        c.append({"task": f"propose-task-{i}", "corpus_label": "real",
                  "source_ref": 100 + i, "source_run_id": 100 + i, "split_side": "propose"})
    for i in range(12):
        c.append({"task": f"holdout-task-{i}", "corpus_label": "real",
                  "source_ref": 200 + i, "source_run_id": 200 + i, "split_side": "holdout"})
    return c


def test_optimizer_never_sees_holdout_tasks(monkeypatch, memdb):
    seen: set[str] = set()

    async def fake_corpus(db, spawn_id, *, baseline_started_at=None):
        return _corpus()
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)

    async def fake_build(spawn_id, **k):
        # rich judge evidence only exists for the propose real runs (100..105)
        return [{"run_id": 100 + i, "task": f"propose-task-{i}", "baseline_output": f"b{i}",
                 "baseline_overall": 6, "baseline_dims": {}} for i in range(6)]
    monkeypatch.setattr(replay_set, "build", fake_build)

    # 1) the optimizer's EDIT generator — record every train task it is handed
    async def fake_edits(spawn, train, *, lr_budget, avoid):
        for it in train:
            seen.add(it["task"])
        # propose exactly one improving edit on the first call, then converge
        return [{"op": "add", "section": "Style", "content": "Be terse."}] if not avoid else []
    monkeypatch.setattr(optimizer, "propose_edits", fake_edits)

    # 2) the running-best snapshot — record every val task it scores the baseline on
    async def fake_val_outputs(spawn_id, doc, val):
        for it in val:
            seen.add(it["task"])
        return {it["run_id"]: "best" for it in val}
    monkeypatch.setattr(evolution_loop, "_val_outputs", fake_val_outputs)

    # 3) the candidate scorer — record every val task the candidate is judged on
    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items,
                        scorer=None, baseline_outputs=None):
        for it in replay_items:
            seen.add(it["task"])
        better = "Be terse." in candidate_prompt
        o = {"better": 1, "worse": 0, "tie": 0} if better else {"better": 0, "worse": 0, "tie": 1}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": better, "reason": "", "aggregate": {"overall": o, "dims": {}}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)

    # the certifying gate passes on holdout (irrelevant which — we only assert isolation)
    def _pass():
        real = {"wins": 12, "losses": 0, "ties": 0, "n": 12, "win_rate": 1.0,
                "p_value": 0.0002, "ci95": [0.7, 1.0], "effective_n": 12}
        empty = {"wins": 0, "losses": 0, "ties": 0, "n": 0, "win_rate": 0.0,
                 "p_value": 1.0, "ci95": [0.0, 0.0], "effective_n": 0}
        return replay_gate.GateResult(
            passed=True, reason="pass", flags=[], real_delta=real, synthetic_delta=empty,
            evidence_tier="strong", pairs=[], excluded_count=0, protected_run_ids=[201])

    async def fake_run_gate(db, *, spawn_id, candidate_prompt, baseline_prompt, corpus,
                            persona="", changed_fields=None, excluded=0):
        # sanity: the gate is handed the SAME corpus, holdout side intact
        holdout = [c for c in corpus if c["split_side"] == "holdout"]
        assert {c["task"] for c in holdout} == _HOLDOUT_TASKS
        return _pass()
    monkeypatch.setattr(replay_gate, "run_gate", fake_run_gate)

    _seed_spawn(memdb)
    res = anyio.run(lambda: evolution_loop.propose_improvement(1, epochs=3))

    # the proposal was produced …
    assert res["proposal_id"] is not None
    # … and every task the optimizer ever touched is a PROPOSE task — ZERO overlap with holdout.
    assert seen, "the optimizer should have seen at least one propose task"
    assert seen & _HOLDOUT_TASKS == set(), f"optimizer leaked holdout tasks: {seen & _HOLDOUT_TASKS}"
    assert seen <= _PROPOSE_TASKS
