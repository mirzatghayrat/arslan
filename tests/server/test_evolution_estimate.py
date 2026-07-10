"""Honest lower-bound cost estimate (S2 E5, acceptance d).

Exercises the estimate math directly against an in-memory DB: the avg-tokens filter
(zero-token + pre-baseline rows excluded) and the full formula shape.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, Run, Spawn
from server.services import evolution_estimate
from server.services.evolution_estimate import AVG_JUDGE_TOKENS, _loop_defaults


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _spawn(db) -> int:
    sp = Spawn(name="S", domain_category="x", system_prompt="P", generation_level=1, config={})
    db.add(sp)
    await db.commit()
    await db.refresh(sp)
    return sp.id


async def _run(db, spawn_id, *, tokens, msg, epoch=1, kind="live", status="scored") -> int:
    r = Run(conversation_id="c", spawn_id=spawn_id, user_message=msg, task_tokens=tokens,
            status=status, kind=kind, epoch=epoch, started_at=datetime.utcnow())
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r.id


async def test_avg_run_tokens_excludes_zero_and_prebaseline(db):
    sid = await _spawn(db)
    await _run(db, sid, tokens=100, msg="t1")
    await _run(db, sid, tokens=200, msg="t2")
    await _run(db, sid, tokens=300, msg="t3")
    await _run(db, sid, tokens=0, msg="z1")            # zero-token: EXCLUDED
    await _run(db, sid, tokens=0, msg="z2")            # zero-token: EXCLUDED
    await _run(db, sid, tokens=999, msg="old", epoch=0)   # pre-baseline: EXCLUDED
    await _run(db, sid, tokens=999, msg="rep", kind="replay")  # replay arm: EXCLUDED

    avg = await evolution_estimate._avg_run_tokens(db, sid)
    assert avg == 200.0   # mean(100, 200, 300) — the 0s and epoch=0/replay never counted


async def test_estimate_formula_matches(db):
    sid = await _spawn(db)
    for i in range(4):
        await _run(db, sid, tokens=100, msg=f"task-{i}")   # 4 scored replayable live runs

    est = await evolution_estimate.estimate(db, sid)
    epochs, lr_budget = _loop_defaults()
    per_pair = epochs * lr_budget + 1

    assert est["pairs"] == 4                         # 4 real, all replayable
    assert est["dispatches"] == 4 * 2 * per_pair     # both arms × (optimizer loop + gate)
    assert est["judge_calls"] == 4 * per_pair * 2    # position-swap = 2 judge calls / compare
    assert est["optimizer_calls"] == epochs
    assert est["synth_calls"] == 0
    assert est["lower_bound"] is True

    avg = 100.0
    assert est["est_tokens"] == int(avg * est["dispatches"] + AVG_JUDGE_TOKENS * est["judge_calls"])


async def test_estimate_zero_corpus(db):
    sid = await _spawn(db)   # no runs at all
    est = await evolution_estimate.estimate(db, sid)
    assert est["pairs"] == 0
    assert est["dispatches"] == 0
    assert est["judge_calls"] == 0
    assert est["est_tokens"] == 0
    assert est["lower_bound"] is True
