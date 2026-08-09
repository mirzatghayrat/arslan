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
from server.services.evolution_estimate import _loop_defaults


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



async def test_estimate_formula_matches(db):
    from server.services import replay_gate
    sid = await _spawn(db)
    for i in range(4):
        await _run(db, sid, tokens=100, msg=f"task-{i}")   # 4 scored replayable live runs (thin)

    # Thin corpus → the estimate PROJECTS the synthetic holdout top-up the real run (mint=True)
    # would perform, WITHOUT minting (read-only). Derive the projected pair count the same way
    # replay_gate.build_corpus + evolution_estimate do, so the formula assertion is exact.
    corpus = await replay_gate.build_corpus(db, sid)   # mint defaults False → no write
    real_holdout = sum(1 for p in corpus
                       if p["corpus_label"] == "real" and p["split_side"] == "holdout")
    total_holdout = sum(1 for p in corpus if p["split_side"] == "holdout")
    proj = (replay_gate.MIN_HOLDOUT_N - total_holdout) if (
        real_holdout < replay_gate.MIN_HOLDOUT_N
        and total_holdout < replay_gate.MIN_HOLDOUT_N) else 0
    expected_pairs = len(corpus) + proj

    est = await evolution_estimate.estimate(db, sid)
    epochs, lr_budget, _val_cap = _loop_defaults()
    per_pair = epochs * lr_budget + 1

    assert est["pairs"] == expected_pairs
    assert est["pairs"] >= replay_gate.MIN_HOLDOUT_N          # thin corpus projected up to floor
    assert est["dispatches"] == expected_pairs * 2 * per_pair  # both arms × (optimizer loop + gate)
    assert est["judge_calls"] == expected_pairs * per_pair * 2  # position-swap = 2 judge / compare
    assert est["optimizer_calls"] == epochs
    assert est["synth_calls"] == 0
    # est_tokens / lower_bound were REMOVED — nothing read them and the label was false.
    # Asserted absent, not just unasserted: re-adding them is the regression to catch.
    assert "est_tokens" not in est
    assert "lower_bound" not in est


async def test_estimate_projects_cold_start_topup_when_no_real(db):
    # E9-b: a spawn with NO real runs would have the real gate mint MIN_HOLDOUT_N synthetic
    # holdout tasks; the preview PROJECTS that cost without minting. No real tokens (avg=0) → the
    # priced cost is the judge floor only. (This is the old "zero corpus" case: no longer zero.)
    from server.services import replay_gate
    sid = await _spawn(db)
    est = await evolution_estimate.estimate(db, sid)
    epochs, lr_budget, _val_cap = _loop_defaults()
    per_pair = epochs * lr_budget + 1
    assert est["pairs"] == replay_gate.MIN_HOLDOUT_N
    assert est["dispatches"] == replay_gate.MIN_HOLDOUT_N * 2 * per_pair
    assert est["judge_calls"] == replay_gate.MIN_HOLDOUT_N * per_pair * 2
    assert "est_tokens" not in est and "lower_bound" not in est


async def test_estimate_does_not_mint_but_projects_topup(db, monkeypatch):
    # BLOCKER regression guard: fetching the cost preview for a thin-corpus spawn must NEVER
    # mint (no DB write, no generation LLM) — yet its pair count must reflect the projected
    # top-up so the previewed cost matches the real topped-up run.
    from sqlalchemy import func, select as sa_select
    from server.db.models import SyntheticTask
    from server.services import replay_gate, synthetic_corpus
    called = {"n": 0}

    async def spy_mint(db_, spawn_id, n, *, adapter=None):
        called["n"] += 1
        return []

    monkeypatch.setattr(synthetic_corpus, "mint_domain_holdout", spy_mint)
    sid = await _spawn(db)
    for i in range(3):
        await _run(db, sid, tokens=100, msg=f"thin-{i}")   # thin corpus below the floor

    before = (await db.execute(sa_select(func.count()).select_from(SyntheticTask))).scalar()
    est = await evolution_estimate.estimate(db, sid)
    after = (await db.execute(sa_select(func.count()).select_from(SyntheticTask))).scalar()

    assert called["n"] == 0                              # estimate NEVER mints (read-only preview)
    assert after == before == 0                          # no SyntheticTask rows written
    assert est["pairs"] >= replay_gate.MIN_HOLDOUT_N     # yet projected cost reaches the floor
