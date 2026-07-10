"""E8: skill_forge candidate eval runs the SAME paired ReplayGate as evolution.

The old `len(val)<min_samples` observation gate (default 8 > val_cap 6 → structurally
impossible) is gone. A candidate is now judged by replay_gate.run_gate over
replay_gate.build_corpus: skill-ON (candidate, arm B) vs skill-OFF (baseline, arm A),
holdout-only. Passing → 'proposed' with the GateResult evidence stored the same way
evolution stores it on a proposal (gate.user_facing()).
"""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillCandidate, Spawn, SyntheticTask
from server.services import skill_forge, replay_gate, replay_run, compare_judge

_GOOD_BODY = (
    "# My Skill\n\n"
    "## Trigger\nUse this when the user asks to do the thing.\n\n"
    "## Steps\n1. Do the first thing.\n2. Do the second thing thoroughly and well.\n"
)

# A baseline long enough that injecting the (short) skill body stays under run_gate's
# 1.25x length cap — so the length threshold isn't what a passing case trips on.
_LONG_PROMPT = "You are a rigorous, evidence-first analyst who verifies claims. " * 30


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'sfe.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def _spawn(maker, prompt="ORIGINAL"):
    async with maker() as db:
        s = Spawn(name="S", domain_category="x", system_prompt=prompt,
                  persona_role="analyst", persona_tone="terse",
                  generation_level=1, config={})
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def _candidate(status="observing"):
    cand = await skill_forge.create_candidate(
        key="my-skill", name="My Skill", category="meta",
        description="does a thing", body=_GOOD_BODY,
    )
    if status != "observing":
        async with db_session.AsyncSessionLocal() as db:
            c = await db.get(SkillCandidate, cand.id)
            c.status = status
            await db.commit()
    return cand.id


async def _synth_holdout(maker, spawn_id, n=12, version=1):
    """Seed `n` active holdout synthetic tasks so build_corpus yields >=10 holdout pairs."""
    async with maker() as db:
        for i in range(n):
            db.add(SyntheticTask(
                spawn_id=spawn_id, version=version, task=f"synthetic task {i}",
                source="domain", split_side="holdout", status="active"))
        await db.commit()


def _passing_gate():
    """A GateResult mirroring what run_gate returns on a clean synthetic-driven pass."""
    synth = {"wins": 12, "losses": 0, "ties": 0, "n": 12,
             "win_rate": 1.0, "p_value": 0.001, "ci95": [0.9, 1.0]}
    return replay_gate.GateResult(
        passed=True, reason="pass", flags=["synthetic_driven"],
        real_delta=replay_gate._empty_delta(), synthetic_delta=synth,
        evidence_tier="strong",
        pairs=[{"corpus_label": "synthetic", "split_side": "holdout", "overall": "b"}
               for _ in range(12)],
        excluded_count=0, protected_run_ids=[101, 102], propose_pairs=[])


def _failing_gate():
    synth = {"wins": 2, "losses": 5, "ties": 3, "n": 7,
             "win_rate": 0.285, "p_value": 1.0, "ci95": [0.0, 0.6]}
    return replay_gate.GateResult(
        passed=False, reason="holdout_winrate", flags=["synthetic_driven"],
        real_delta=replay_gate._empty_delta(), synthetic_delta=synth,
        evidence_tier="weak",
        pairs=[{"corpus_label": "synthetic", "split_side": "holdout", "overall": "a"}],
        excluded_count=0, protected_run_ids=[], propose_pairs=[])


@pytest.mark.asyncio
async def test_gate_passes_becomes_proposed_deadlock_gone(maker, monkeypatch):
    """Deadlock proof: with >=10 HOLDOUT pairs (12 synthetic here — more than the old
    val_cap of 6 that min_samples=8 could never clear), a candidate whose skill-ON arm
    wins reaches 'proposed'. Exercises the REAL build_corpus + run_gate; only the
    per-arm dispatch and the judge are stubbed (no live LLM)."""
    sid = await _spawn(maker, prompt=_LONG_PROMPT)
    cid = await _candidate()
    await _synth_holdout(maker, sid, n=12)

    async def fake_snapshot(db, *, spawn_id, conversation_id, task=""):
        return {}

    async def fake_run_arm(db, *, spawn_id, task, system_prompt, ambient, **k):
        return {"run_id": None, "output": "answer", "evidence": ""}

    async def fake_compare(*, task, persona, output_a, output_b, item=None,
                           evidence_a="", evidence_b=""):
        # candidate (arm B) wins on every dimension and overall
        return {"dimensions": {"fabrication": "b", "identity": "b", "completion": "b"},
                "overall": "b", "position_sensitive": False, "margin": 1.0}

    monkeypatch.setattr(replay_run, "snapshot_ambient", fake_snapshot)
    monkeypatch.setattr(replay_run, "run_arm", fake_run_arm)
    monkeypatch.setattr(compare_judge, "compare", fake_compare)

    res = await skill_forge.evaluate_candidate(cid, sid)
    assert res["ok"] is True
    assert res["status"] == "proposed"          # <-- reachable: the deadlock is gone
    assert res["gate"]["passed"] is True

    async with maker() as db:
        c = await db.get(SkillCandidate, cid)
    assert c.status == "proposed"
    # Evidence stored in the SAME shape evolution stores on a proposal (user_facing()).
    ev = c.evidence
    assert set(ev) >= {"passed", "reason", "real_delta", "synthetic_delta",
                       "evidence_tier", "pairs", "protected_run_ids", "excluded_count"}
    assert ev["passed"] is True
    assert ev["synthetic_delta"]["n"] == 12
    assert ev["synthetic_delta"]["win_rate"] == 1.0
    assert len(ev["pairs"]) == 12


@pytest.mark.asyncio
async def test_skill_forge_uses_shared_run_gate_with_skill_on_off(maker, monkeypatch):
    """skill_forge and evolution go through the IDENTICAL replay_gate.run_gate. Capture
    its kwargs and prove skill_forge feeds skill-ON (candidate) vs skill-OFF (baseline)."""
    sid = await _spawn(maker, prompt="You are the base prompt.")
    cid = await _candidate()

    captured = {}

    async def fake_run_gate(db, *, spawn_id, candidate_prompt, baseline_prompt,
                            corpus, persona="", **k):
        captured.update(spawn_id=spawn_id, candidate_prompt=candidate_prompt,
                        baseline_prompt=baseline_prompt, persona=persona)
        return _failing_gate()

    monkeypatch.setattr(replay_gate, "run_gate", fake_run_gate)

    await skill_forge.evaluate_candidate(cid, sid)

    assert captured["spawn_id"] == sid
    # skill-ON: candidate arm faithfully injects the body under the techniques header
    assert "Your techniques:" in captured["candidate_prompt"]
    assert "## Trigger" in captured["candidate_prompt"]
    # skill-OFF: baseline arm is exactly the spawn's current prompt, no injection
    assert captured["baseline_prompt"] == "You are the base prompt."
    assert "Your techniques:" not in captured["baseline_prompt"]


@pytest.mark.asyncio
async def test_gate_fails_stays_observing(maker, monkeypatch):
    sid = await _spawn(maker)
    cid = await _candidate()

    async def fake_run_gate(db, **k):
        return _failing_gate()
    monkeypatch.setattr(replay_gate, "run_gate", fake_run_gate)

    res = await skill_forge.evaluate_candidate(cid, sid)
    assert res["ok"] is True
    assert res["status"] == "observing"
    assert res["gate"]["passed"] is False
    assert res["gate"]["reason"] == "holdout_winrate"

    async with maker() as db:
        c = await db.get(SkillCandidate, cid)
    assert c.status == "observing"
    assert c.evidence["passed"] is False
    assert c.evidence["reason"] == "holdout_winrate"


@pytest.mark.asyncio
async def test_non_observing_candidate_returns_not_ok(maker):
    sid = await _spawn(maker)
    cid = await _candidate(status="promoted")
    res = await skill_forge.evaluate_candidate(cid, sid)
    assert res["ok"] is False
    assert "promoted" in res["reason"]


@pytest.mark.asyncio
async def test_missing_spawn_returns_not_ok(maker):
    cid = await _candidate()
    res = await skill_forge.evaluate_candidate(cid, 9999)
    assert res["ok"] is False
    assert "spawn not found" in res["reason"]


@pytest.mark.asyncio
async def test_gate_exception_degrades_to_no_pass(maker, monkeypatch):
    sid = await _spawn(maker)
    cid = await _candidate()

    async def boom(*a, **k):
        raise RuntimeError("replay down")
    monkeypatch.setattr(replay_gate, "run_gate", boom)

    res = await skill_forge.evaluate_candidate(cid, sid)  # must not raise
    assert res["ok"] is True
    assert res["status"] == "observing"
    assert res["gate"]["passed"] is False
    assert "gate failed" in res["gate"]["reason"]

    async with maker() as db:
        c = await db.get(SkillCandidate, cid)
    assert c.status == "observing"
    assert "gate failed" in c.evidence["reason"]
