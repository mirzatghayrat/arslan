import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, EvolutionProposal, Spawn
from server.services import evolution_loop, optimizer, evaluator, replay_set


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


def _await(value):
    async def _a():
        return value
    return _a()


async def test_propose_persists_proposal(memdb, monkeypatch):
    sid = await _spawn(memdb)
    monkeypatch.setattr(replay_set, "build", lambda spawn_id, *, cap=5: _await([{"run_id": 1, "task": "t",
        "baseline_output": "b", "baseline_overall": 6.0, "baseline_dims": {}}]))
    async def fake_propose(spawn, items): return "CANDIDATE"
    monkeypatch.setattr(optimizer, "propose", fake_propose)
    async def fake_eval(*, spawn_id, persona, candidate_prompt, replay_items):
        return {"items": [], "aggregate": {"overall": {"better": 1, "worse": 0, "tie": 0},
                "dims": {}}, "gate": {"passed": True, "reason": "ok", "aggregate": {}}}
    monkeypatch.setattr(evaluator, "evaluate", fake_eval)

    out = await evolution_loop.propose_improvement(sid)
    assert out["proposal_id"] is not None
    assert out["gate"]["passed"] is True
    async with memdb() as db:
        p = await db.get(EvolutionProposal, out["proposal_id"])
    assert p.candidate_prompt == "CANDIDATE" and p.gate_passed is True and p.status == "proposed"


async def test_propose_empty_replay_no_proposal(memdb, monkeypatch):
    sid = await _spawn(memdb)
    monkeypatch.setattr(replay_set, "build", lambda spawn_id, *, cap=5: _await([]))
    out = await evolution_loop.propose_improvement(sid)
    assert out["proposal_id"] is None and out["gate"]["passed"] is False


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
