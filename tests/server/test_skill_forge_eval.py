import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillCandidate, Spawn
from server.services import skill_forge, replay_set, evaluator

_GOOD_BODY = (
    "# My Skill\n\n"
    "## Trigger\nUse this when the user asks to do the thing.\n\n"
    "## Steps\n1. Do the first thing.\n2. Do the second thing thoroughly and well.\n"
)


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


def _val(n):
    return [{"run_id": i, "task": f"t{i}", "baseline_output": f"b{i}",
             "baseline_overall": 6, "baseline_dims": {}} for i in range(n)]


def _patch_no_dispatch(monkeypatch):
    """Stub the skill-off baseline dispatch so no real LLM/dispatch runs."""
    async def fake_val_outputs(spawn_id, system_prompt_override, val):
        return {it["run_id"]: "off-output" for it in val}
    monkeypatch.setattr(skill_forge, "_val_outputs", fake_val_outputs)


@pytest.mark.asyncio
async def test_insufficient_samples_stays_observing(maker, monkeypatch):
    sid = await _spawn(maker)
    cid = await _candidate()

    async def fake_split(spawn_id, **k):
        return {"train": [], "val": _val(3)}  # < min_samples=8
    monkeypatch.setattr(replay_set, "build_split", fake_split)

    res = await skill_forge.evaluate_candidate(cid, sid, min_samples=8)
    assert res["ok"] is True
    assert res["status"] == "observing"
    assert res["gate"]["passed"] is False
    assert "insufficient" in res["gate"]["reason"]

    async with maker() as db:
        c = await db.get(SkillCandidate, cid)
    assert c.status == "observing"
    assert c.samples == {"observed": 3, "need": 8}
    assert c.evidence["gate"]["observed"] == 3


@pytest.mark.asyncio
async def test_gate_passes_becomes_proposed(maker, monkeypatch):
    sid = await _spawn(maker)
    cid = await _candidate()
    _patch_no_dispatch(monkeypatch)

    val = _val(8)

    async def fake_split(spawn_id, **k):
        return {"train": [], "val": val}
    monkeypatch.setattr(replay_set, "build_split", fake_split)

    seen = {}

    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items,
                        scorer=None, baseline_outputs=None):
        seen["prompt"] = candidate_prompt
        o = {"better": 5, "worse": 0, "tie": 3}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": True, "reason": "improves", "aggregate": {"overall": o}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)

    res = await skill_forge.evaluate_candidate(cid, sid, min_samples=8)
    assert res["ok"] is True
    assert res["status"] == "proposed"
    assert res["gate"]["passed"] is True
    # skill-on prompt faithfully injects the candidate body under a techniques header
    assert "Your techniques:" in seen["prompt"]
    assert "## Trigger" in seen["prompt"]

    async with maker() as db:
        c = await db.get(SkillCandidate, cid)
    assert c.status == "proposed"
    assert c.samples == [it["run_id"] for it in val]
    assert c.evidence["gate"]["passed"] is True


@pytest.mark.asyncio
async def test_gate_fails_stays_observing(maker, monkeypatch):
    sid = await _spawn(maker)
    cid = await _candidate()
    _patch_no_dispatch(monkeypatch)

    val = _val(8)

    async def fake_split(spawn_id, **k):
        return {"train": [], "val": val}
    monkeypatch.setattr(replay_set, "build_split", fake_split)

    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items,
                        scorer=None, baseline_outputs=None):
        o = {"better": 0, "worse": 2, "tie": 6}
        return {"items": [], "aggregate": {"overall": o, "dims": {}},
                "gate": {"passed": False, "reason": "not better", "aggregate": {"overall": o}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)

    res = await skill_forge.evaluate_candidate(cid, sid, min_samples=8)
    assert res["ok"] is True
    assert res["status"] == "observing"
    assert res["gate"]["passed"] is False

    async with maker() as db:
        c = await db.get(SkillCandidate, cid)
    assert c.status == "observing"
    assert c.evidence["gate"]["passed"] is False
    assert c.samples == [it["run_id"] for it in val]


@pytest.mark.asyncio
async def test_non_observing_candidate_returns_not_ok(maker, monkeypatch):
    sid = await _spawn(maker)
    cid = await _candidate(status="promoted")
    res = await skill_forge.evaluate_candidate(cid, sid, min_samples=8)
    assert res["ok"] is False
    assert "promoted" in res["reason"]


@pytest.mark.asyncio
async def test_missing_spawn_returns_not_ok(maker):
    cid = await _candidate()
    res = await skill_forge.evaluate_candidate(cid, 9999, min_samples=8)
    assert res["ok"] is False
    assert "spawn not found" in res["reason"]


@pytest.mark.asyncio
async def test_eval_failure_degrades_to_no_pass(maker, monkeypatch):
    sid = await _spawn(maker)
    cid = await _candidate()
    _patch_no_dispatch(monkeypatch)

    async def fake_split(spawn_id, **k):
        return {"train": [], "val": _val(8)}
    monkeypatch.setattr(replay_set, "build_split", fake_split)

    async def boom(*a, **k):
        raise RuntimeError("judge down")
    monkeypatch.setattr(evaluator, "evaluate", boom)

    res = await skill_forge.evaluate_candidate(cid, sid, min_samples=8)  # must not raise
    assert res["ok"] is True
    assert res["status"] == "observing"
    assert res["gate"]["passed"] is False

    async with maker() as db:
        c = await db.get(SkillCandidate, cid)
    assert c.status == "observing"
