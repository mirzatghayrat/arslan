"""E9-b Task 4a — the shared evolution_diagnostics service (one source of truth for the CLI
+ the GET /spawns/{id}/evolution/diagnosis endpoint). Read-only: a diagnosis NEVER mints
synthetic tasks (build_corpus mint defaults to False), so merely inspecting a spawn cannot
mutate its corpus. The verdict is a stable machine `verdict_code` + a params dict (numbers /
tool names / attempt id — never English prose)."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, Run, Spawn, SyntheticTask


@pytest.fixture
async def memdb(monkeypatch):
    from server.db import session as db_session

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


def _att(**kw):
    """A fake attempt row for the pure _verdict_code ordering tests."""
    kw.setdefault("outcome", None)
    kw.setdefault("started_at", None)
    kw.setdefault("reason", "")
    kw.setdefault("id", 1)
    return SimpleNamespace(**kw)


# ── _verdict_code: pure, first-match-wins ordering + the 10 stable codes ────────────────

def test_verdict_code_drought_no_runs():
    from server.services import evolution_diagnostics as ed
    code, params = ed._verdict_code(
        total_scored=0, replayable=0, non_replayable=0, offending_tools={},
        baseline=None, scored_ge_baseline=0, holdout_ceiling=0, real_holdout=0,
        propose_count=0, attempts=[])
    assert code == "drought_no_runs" and params == {}


def test_verdict_code_drought_non_replayable_starves_propose():
    from server.services import evolution_diagnostics as ed
    code, params = ed._verdict_code(
        total_scored=8, replayable=3, non_replayable=5,
        offending_tools={"mcp_x__do": 5}, baseline=None, scored_ge_baseline=8,
        holdout_ceiling=2, real_holdout=2, propose_count=1, attempts=[])
    assert code == "drought_non_replayable"
    assert params["non_replayable"] == 5 and params["replayable"] == 3
    assert params["min"] == ed.MIN_HOLDOUT_N and params["tools"] == {"mcp_x__do": 5}


def test_verdict_code_drought_too_few():
    from server.services import evolution_diagnostics as ed
    code, params = ed._verdict_code(
        total_scored=6, replayable=6, non_replayable=0, offending_tools={},
        baseline=None, scored_ge_baseline=6, holdout_ceiling=2, real_holdout=2,
        propose_count=4, attempts=[])
    assert code == "drought_too_few"
    assert params["total_scored"] == 6 and params["min"] == ed.MIN_HOLDOUT_N


def test_verdict_code_baseline_flooring():
    from server.services import evolution_diagnostics as ed
    code, params = ed._verdict_code(
        total_scored=20, replayable=20, non_replayable=0, offending_tools={},
        baseline=datetime(2026, 7, 11), scored_ge_baseline=4, holdout_ceiling=2,
        real_holdout=2, propose_count=2, attempts=[])
    assert code == "baseline_flooring"
    assert params["scored_ge_baseline"] == 4 and params["min"] == ed.MIN_HOLDOUT_N


def test_verdict_code_holdout_via_synthetic_topup_replaces_old_drought_split():
    """E9-b Task 3 interaction: a thin real holdout is NO LONGER a blocker — the mint=True
    top-up fills it to MIN_HOLDOUT_N at evolve time, so the diagnosis is INFORMATIONAL."""
    from server.services import evolution_diagnostics as ed
    code, params = ed._verdict_code(
        total_scored=12, replayable=12, non_replayable=0, offending_tools={},
        baseline=None, scored_ge_baseline=12, holdout_ceiling=6, real_holdout=6,
        propose_count=6, attempts=[])
    assert code == "holdout_via_synthetic_topup"      # NOT "drought_holdout_split"
    assert params == {"real_holdout": 6, "min": ed.MIN_HOLDOUT_N}


def test_verdict_code_in_flight_hung_wins_over_everything():
    from server.services import evolution_diagnostics as ed
    old = datetime.utcnow().replace(year=2000)
    code, params = ed._verdict_code(
        total_scored=0, replayable=0, non_replayable=0, offending_tools={},
        baseline=None, scored_ge_baseline=0, holdout_ceiling=0, real_holdout=0,
        propose_count=0, attempts=[_att(id=9, outcome=None, started_at=old)])
    assert code == "in_flight_hung"
    assert params["attempt_id"] == 9 and params["age_min"] > 0


def test_verdict_code_gate_failure_and_skipped_budget_and_eligible():
    from server.services import evolution_diagnostics as ed
    common = dict(total_scored=20, replayable=20, non_replayable=0, offending_tools={},
                  baseline=None, scored_ge_baseline=20, holdout_ceiling=12, real_holdout=12,
                  propose_count=8)
    gate = _att(id=3, outcome="failed", reason="holdout_winrate")
    code, params = ed._verdict_code(attempts=[gate], **common)
    assert code == "gate_failure" and params == {"attempt_id": 3, "reason": "holdout_winrate"}

    budget = _att(id=4, outcome="skipped_budget", reason="estimate 9 tokens exceeds budget 5")
    code, _ = ed._verdict_code(attempts=[budget], **common)
    assert code == "skipped_budget"

    passed = _att(id=5, outcome="passed", reason="gate passed")
    code, params = ed._verdict_code(attempts=[passed], **common)
    assert code == "eligible_looking" and params == {}


# ── diagnose_spawn: numeric fields + read-only + the top-up verdict ─────────────────────

async def test_diagnose_spawn_topup_verdict_and_read_only(memdb):
    from server.services import evolution_diagnostics as ed
    async with memdb() as db:
        db.add(Spawn(id=1, name="RA", domain_category="research", system_prompt="p",
                     generation_level=1))
        # 12 replayable real runs, NO synthetics → holdout split < 10, real holdout < 10.
        for i in range(12):
            db.add(Run(conversation_id="c", spawn_id=1, user_message=f"t{i}",
                       status="scored", kind="live", epoch=1, created_at=datetime(2026, 7, 1)))
        await db.commit()

    async with memdb() as db:
        spawn = await db.get(Spawn, 1)
        d = await ed.diagnose_spawn(db, spawn)

    assert d["total_scored"] == 12 and d["replayable"] == 12 and d["non_replayable"] == 0
    assert d["holdout_ceiling"] < ed.MIN_HOLDOUT_N          # un-topped (mint=False) ceiling
    assert d["real_holdout"] == d["holdout_ceiling"]        # all holdout pairs are real
    assert d["effective_holdout"] == ed.MIN_HOLDOUT_N       # projected after the evolve top-up
    assert d["verdict_code"] == "holdout_via_synthetic_topup"
    assert d["verdict_params"] == {"real_holdout": d["real_holdout"], "min": ed.MIN_HOLDOUT_N}
    assert d["min_holdout_n"] == ed.MIN_HOLDOUT_N
    assert d["generation_level"] == 1
    assert isinstance(d["last_attempts"], list) and d["last_attempts"] == []
    assert isinstance(d["auto_on"], bool) and "max_est_tokens" in d

    # READ-ONLY: the diagnosis never minted a synthetic task.
    async with memdb() as db:
        n = (await db.execute(select(func.count()).select_from(SyntheticTask))).scalar()
    assert n == 0


async def test_diagnose_spawn_no_runs_is_genuine_drought(memdb):
    from server.services import evolution_diagnostics as ed
    async with memdb() as db:
        db.add(Spawn(id=2, name="Empty", domain_category="x", system_prompt="p"))
        await db.commit()
    async with memdb() as db:
        spawn = await db.get(Spawn, 2)
        d = await ed.diagnose_spawn(db, spawn)
    assert d["total_scored"] == 0 and d["verdict_code"] == "drought_no_runs"
