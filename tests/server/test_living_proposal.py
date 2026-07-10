"""Living-proposal refresh — accumulation, gate-flip, and staleness (S2 E4 decision B.2).

Stubs build_corpus (new task supply) and run_gate (the new pairs) so the tests exercise the
ACCUMULATION + threshold-flip logic in refresh_proposal, not a real LLM. recompute_verdict
(the union math) is the real code under test.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, EvolutionProposal, Spawn
from server.services import evolution_loop, replay_gate, skill_doc
from server.services.evolution_loop import _sha
from server.services.replay_gate import GateResult

DIMS = ("fabrication", "identity", "completion")
PROMPT = "## Role\nYou are an analyst."


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


def _pair(overall: str, corpus_label: str = "real"):
    return {"corpus_label": corpus_label, "split_side": "holdout", "overall": overall,
            "per_dim": {d: overall for d in DIMS}, "task_hash": overall}


def _empty_gate(new_pairs):
    """A GateResult whose only meaningful field for refresh is `.pairs` (the new holdout)."""
    return GateResult(passed=True, reason="pass", flags=[], real_delta={}, synthetic_delta={},
                      evidence_tier="weak", pairs=new_pairs, excluded_count=0,
                      protected_run_ids=[])


async def _spawn(db, prompt=PROMPT) -> int:
    s = Spawn(name="S", domain_category="x", system_prompt=prompt, generation_level=1, config={})
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s.id


async def _open_proposal(db, spawn_id, *, prompt=PROMPT, old_pairs) -> int:
    base_sha = _sha(skill_doc.apply_edits(prompt, []))
    p = EvolutionProposal(
        spawn_id=spawn_id, candidate_prompt="CANDIDATE", gate_passed=True, status="open",
        base_prompt_sha=base_sha,
        evidence={"pairs": old_pairs, "real_delta": {"win_rate": 1.0}, "flags": []},
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p.id


async def test_accumulation_flips_gate_but_stays_open(db, monkeypatch):
    sid = await _spawn(db)
    old_pairs = [_pair("b") for _ in range(12)]          # 12 real holdout WINS → was passing
    pid = await _open_proposal(db, sid, old_pairs=old_pairs)

    async def fake_corpus(db_, spawn_id, *, baseline_started_at=None):
        return [{"corpus_label": "real", "split_side": "holdout", "task": f"t{i}"}
                for i in range(6)]                        # 6 NEW real tasks (>= 5)

    new_losses = [_pair("a") for _ in range(12)]          # 12 real holdout LOSSES arrive
    async def fake_run_gate(db_, **k):
        return _empty_gate(new_losses)

    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)
    monkeypatch.setattr(replay_gate, "run_gate", fake_run_gate)

    res = await evolution_loop.refresh_proposal(db, pid)
    assert res["ok"] is True and res["refreshed"] is True

    # 12 wins + 12 losses → win-rate 0.5 < 0.60 → gate flips FAILING, flagged, still OPEN.
    prop = await db.get(EvolutionProposal, pid)
    assert prop.gate_passed is False
    assert prop.status == "open"                          # human decides去留 — not auto-killed
    assert "no_longer_passing" in prop.evidence["flags"]
    assert len(prop.evidence["pairs"]) == 24              # accumulated, not replaced
    assert prop.evidence["real_delta"]["n"] == 24


async def test_refresh_flags_sequential_uncorrected(db, monkeypatch):
    # FIX 4b: a living-proposal refresh re-looks at the accumulated p-value with no
    # multiple-comparison correction (optional stopping). Any refresh must set the
    # 'sequential_uncorrected' flag and bump a refresh_count so the card can say so.
    sid = await _spawn(db)
    pid = await _open_proposal(db, sid, old_pairs=[_pair("b") for _ in range(12)])

    async def fake_corpus(db_, spawn_id, *, baseline_started_at=None):
        return [{"corpus_label": "real", "split_side": "holdout", "task": f"t{i}"}
                for i in range(6)]                        # 6 NEW real tasks (>= 5)
    async def fake_run_gate(db_, **k):
        return _empty_gate([_pair("b") for _ in range(6)])   # still winning
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)
    monkeypatch.setattr(replay_gate, "run_gate", fake_run_gate)

    res = await evolution_loop.refresh_proposal(db, pid)
    assert res["refreshed"] is True
    prop = await db.get(EvolutionProposal, pid)
    assert "sequential_uncorrected" in prop.evidence["flags"]
    assert prop.evidence["refresh_count"] == 1
    assert res["flags"].count("sequential_uncorrected") == 1

    # a SECOND refresh bumps the counter; the flag is present exactly once (not duplicated).
    await evolution_loop.refresh_proposal(db, pid)
    prop2 = await db.get(EvolutionProposal, pid)
    assert prop2.evidence["refresh_count"] == 2
    assert prop2.evidence["flags"].count("sequential_uncorrected") == 1


async def test_prompt_drift_marks_stale(db, monkeypatch):
    sid = await _spawn(db, prompt=PROMPT)
    pid = await _open_proposal(db, sid, prompt=PROMPT, old_pairs=[_pair("b") for _ in range(12)])

    # The spawn's prompt drifts away from base_prompt_sha.
    spawn = await db.get(Spawn, sid)
    spawn.system_prompt = "## Role\nYou are a DIFFERENT analyst now."
    await db.commit()

    called = {"corpus": False}
    async def fake_corpus(db_, spawn_id, *, baseline_started_at=None):
        called["corpus"] = True
        return []
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)

    res = await evolution_loop.refresh_proposal(db, pid)
    assert res["status"] == "stale"
    prop = await db.get(EvolutionProposal, pid)
    assert prop.status == "stale"
    assert called["corpus"] is False   # staleness short-circuits before any replay


async def test_refresh_noop_when_too_few_new_tasks(db, monkeypatch):
    sid = await _spawn(db)
    pid = await _open_proposal(db, sid, old_pairs=[_pair("b") for _ in range(12)])

    async def fake_corpus(db_, spawn_id, *, baseline_started_at=None):
        return [{"corpus_label": "real", "split_side": "holdout", "task": f"t{i}"}
                for i in range(4)]   # only 4 new (< 5) → refresh is a no-op

    ran = {"gate": False}
    async def fake_run_gate(db_, **k):
        ran["gate"] = True
        return _empty_gate([])
    monkeypatch.setattr(replay_gate, "build_corpus", fake_corpus)
    monkeypatch.setattr(replay_gate, "run_gate", fake_run_gate)

    res = await evolution_loop.refresh_proposal(db, pid)
    assert res["refreshed"] is False
    assert ran["gate"] is False
    prop = await db.get(EvolutionProposal, pid)
    assert prop.gate_passed is True and prop.status == "open"   # untouched
