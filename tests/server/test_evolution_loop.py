import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, EvolutionProposal, Spawn
from server.services import evolution_loop, optimizer, evaluator, replay_gate, replay_set


def _gate_result(passed):
    """A stub GateResult standing in for the paired ReplayGate final decision."""
    empty = {"wins": 0, "losses": 0, "ties": 0, "n": 0,
             "win_rate": 0.0, "p_value": 1.0, "ci95": [0.0, 0.0]}
    real = {"wins": 11, "losses": 0, "ties": 0, "n": 11,
            "win_rate": 1.0, "p_value": 0.0004, "ci95": [0.7, 1.0]}
    return replay_gate.GateResult(
        passed=passed, reason=("pass" if passed else "holdout_winrate"), flags=[],
        real_delta=(real if passed else empty), synthetic_delta=dict(empty),
        evidence_tier=("strong" if passed else "weak"), pairs=[],
        excluded_count=0, protected_run_ids=[101, 102])


def _patch_gate(monkeypatch, *, passed):
    """Stub build_corpus + run_gate so the loop's FINAL decision is deterministic."""
    async def fake_corpus(db, spawn_id, *, baseline_started_at=None):
        return replay_gate.Corpus()
    async def fake_run_gate(db, *, spawn_id, candidate_prompt, baseline_prompt, corpus,
                            persona="", changed_fields=None, excluded=0):
        return _gate_result(passed)
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)
    monkeypatch.setattr(replay_gate, "run_gate", fake_run_gate)


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _spawn(Session, prompt="ORIGINAL"):
    async with Session() as db:
        s = Spawn(name="S", domain_category="x", system_prompt=prompt, generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


# ── multi-epoch propose_improvement tests ────────────────────────────────────


class _Spawn:
    id = 1
    name = "fin"
    persona_role = "analyst"
    persona_tone = "terse"
    system_prompt = "## Role\nYou are an analyst."


def _seed_spawn(Session, spawn_like):
    """Insert a real Spawn row (id=1 in the fresh in-memory DB) mirroring spawn_like."""
    async def _ins():
        async with Session() as db:
            s = Spawn(name=spawn_like.name, domain_category="x",
                      persona_role=spawn_like.persona_role, persona_tone=spawn_like.persona_tone,
                      system_prompt=spawn_like.system_prompt, generation_level=1, config={})
            db.add(s)
            await db.commit()
            await db.refresh(s)
            return s.id
    return anyio.run(_ins)


def _split():
    return {"train": [{"run_id": 1, "task": "t1", "baseline_output": "b1"}],
            "val": [{"run_id": 2, "task": "t2", "baseline_output": "b2",
                     "baseline_overall": 6, "baseline_dims": {}}]}


def _patch_common(monkeypatch, *, split, edits_by_epoch):
    async def fake_split(spawn_id, **k): return split
    monkeypatch.setattr(replay_set, "build_split", fake_split)
    async def fake_val_outputs(spawn_id, doc, val): return {it["run_id"]: "best" for it in val}
    monkeypatch.setattr(evolution_loop, "_val_outputs", fake_val_outputs)
    seq = list(edits_by_epoch)
    seen_avoid = []
    async def fake_edits(spawn, train, *, lr_budget, avoid):
        seen_avoid.append(list(avoid))
        return seq.pop(0) if seq else []
    monkeypatch.setattr(optimizer, "propose_edits", fake_edits)
    return seen_avoid


def test_loop_accepts_improving_edit_and_proposes(monkeypatch, memdb):
    _patch_common(monkeypatch, split=_split(),
                  edits_by_epoch=[[{"op": "add", "section": "Style", "content": "Be terse."}], []])
    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items, scorer=None, baseline_outputs=None):
        better = "Be terse." in candidate_prompt
        o = {"better": 1, "worse": 0, "tie": 0} if better else {"better": 0, "worse": 0, "tie": 1}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": better, "reason": "", "aggregate": {"overall": o, "dims": {}}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)
    _patch_gate(monkeypatch, passed=True)          # ReplayGate passes on holdout
    _seed_spawn(memdb, _Spawn)
    res = anyio.run(lambda: evolution_loop.propose_improvement(1, epochs=2))
    assert res["proposal_id"] is not None
    assert res["gate"]["passed"] is True
    assert res["evidence"]["diff"] == [{"op": "add", "section": "Style", "content": "Be terse."}]
    # The persisted proposal is a LIVING one: status='open', base_prompt_sha pinned,
    # gate evidence (protected_run_ids) carried on it for E2's redact exemption.
    async def _read():
        async with memdb() as db:
            return await db.get(EvolutionProposal, res["proposal_id"])
    prop = anyio.run(_read)
    assert prop.status == "open"
    assert prop.base_prompt_sha and len(prop.base_prompt_sha) == 64
    assert prop.evidence["protected_run_ids"] == [101, 102]
    assert "real_delta" in prop.evidence and "synthetic_delta" in prop.evidence


def test_loop_rejects_and_buffers(monkeypatch, memdb):
    seen_avoid = _patch_common(monkeypatch, split=_split(),
                               edits_by_epoch=[[{"op": "add", "section": "X", "content": "bad"}],
                                               [{"op": "add", "section": "Y", "content": "also"}]])
    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items, scorer=None, baseline_outputs=None):
        o = {"better": 0, "worse": 0, "tie": 1}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": False, "reason": "", "aggregate": {"overall": o, "dims": {}}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)
    _seed_spawn(memdb, _Spawn)
    res = anyio.run(lambda: evolution_loop.propose_improvement(1, epochs=2))
    assert res["proposal_id"] is None
    assert {"op": "add", "section": "X", "content": "bad"} in seen_avoid[1]  # rejected edit buffered into next epoch


def test_loop_no_op_on_insufficient(monkeypatch, memdb):
    async def fake_split(spawn_id, **k): return {"train": [], "val": []}
    monkeypatch.setattr(replay_set, "build_split", fake_split)
    res = anyio.run(lambda: evolution_loop.propose_improvement(1, epochs=2))
    assert res["proposal_id"] is None and res["gate"]["passed"] is False


def test_loop_final_gate_fails_on_holdout(monkeypatch, memdb):
    # An edit is accepted against the running-best propose signal, but the paired
    # ReplayGate FAILS on holdout → no proposal (the gate, not the optimizer, decides).
    _patch_common(monkeypatch, split=_split(),
                  edits_by_epoch=[[{"op": "add", "section": "Style", "content": "Be terse."}], []])
    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items, scorer=None, baseline_outputs=None):
        better = "Be terse." in candidate_prompt
        o = {"better": 1, "worse": 0, "tie": 0} if better else {"better": 0, "worse": 0, "tie": 1}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": better, "reason": "", "aggregate": {"overall": o, "dims": {}}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)
    _patch_gate(monkeypatch, passed=False)         # ReplayGate FAILS on holdout
    _seed_spawn(memdb, _Spawn)
    res = anyio.run(lambda: evolution_loop.propose_improvement(1, epochs=2))
    assert res["proposal_id"] is None
    assert res["gate"]["passed"] is False and res["gate"]["reason"] == "holdout_winrate"


def test_loop_degrades_on_dispatch_failure(monkeypatch, memdb):
    async def fake_split(spawn_id, **k): return _split()
    monkeypatch.setattr(replay_set, "build_split", fake_split)
    async def boom(spawn_id, doc, val): raise RuntimeError("dispatch down")
    monkeypatch.setattr(evolution_loop, "_val_outputs", boom)
    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items, scorer=None, baseline_outputs=None):
        o = {"better": 0, "worse": 0, "tie": 1}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": False, "reason": "", "aggregate": {"overall": o, "dims": {}}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)
    _seed_spawn(memdb, _Spawn)
    res = anyio.run(lambda: evolution_loop.propose_improvement(1, epochs=2))  # must not raise
    assert res["proposal_id"] is None


# ── confirm_proposal tests (unchanged behavior) ──────────────────────────────


async def test_confirm_promotes_when_gate_passed(memdb, monkeypatch):
    sid = await _spawn(memdb, prompt="ORIGINAL")
    async with memdb() as db:
        p = EvolutionProposal(spawn_id=sid, candidate_prompt="NEWP", gate_passed=True,
                              evidence={}, status="proposed")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        pid = p.id

    res = await evolution_loop.confirm_proposal(pid)
    assert res["ok"] is True
    async with memdb() as db:
        s = await db.get(Spawn, sid)
        p = await db.get(EvolutionProposal, pid)
    assert s.system_prompt == "NEWP"
    assert s.generation_level == 2
    assert s.config["prompt_history"][0]["old_prompt"] == "ORIGINAL"
    assert p.status == "promoted"


async def test_confirm_refuses_when_gate_failed(memdb, monkeypatch):
    sid = await _spawn(memdb, prompt="ORIGINAL")
    async with memdb() as db:
        p = EvolutionProposal(spawn_id=sid, candidate_prompt="NEWP", gate_passed=False,
                              evidence={}, status="proposed")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        pid = p.id
    res = await evolution_loop.confirm_proposal(pid)
    assert res["ok"] is False
    async with memdb() as db:
        s = await db.get(Spawn, sid)
    assert s.system_prompt == "ORIGINAL"


async def test_confirm_twice_is_noop(memdb, monkeypatch):
    sid = await _spawn(memdb, prompt="ORIGINAL")
    async with memdb() as db:
        p = EvolutionProposal(spawn_id=sid, candidate_prompt="NEWP", gate_passed=True,
                              evidence={}, status="proposed")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        pid = p.id

    first = await evolution_loop.confirm_proposal(pid)
    assert first["ok"] is True
    second = await evolution_loop.confirm_proposal(pid)
    assert second["ok"] is False
    assert "already" in second["reason"]

    # spawn promoted exactly once: generation_level bumped to 2 (not 3)
    async with memdb() as db:
        s = await db.get(Spawn, sid)
    assert s.generation_level == 2
