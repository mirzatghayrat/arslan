"""E2 (audit CRITICAL-6): the retention sweep must NOT redact a replay Run cited by a
non-'rejected' EvolutionProposal (evidence.protected_run_ids) — that two-arm text is the
evidence the promotion card's win-rate traces to. Unreferenced old runs are still redacted,
and a run cited only by a REJECTED proposal is NOT exempt."""
import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, EvolutionProposal, Run, Spawn


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


_OLD = datetime.datetime.utcnow() - datetime.timedelta(days=40)


async def _old_replay_run(db, spawn_id: int) -> int:
    run = Run(conversation_id="c1", spawn_id=spawn_id, user_message="t",
              started_at=_OLD, created_at=_OLD, status="replayed",
              kind="replay", epoch=1, system_prompt="SECRET SYS", final_output="arm output")
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run.id


async def _proposal(db, spawn_id: int, *, status: str, protected: list[int]) -> None:
    db.add(EvolutionProposal(
        spawn_id=spawn_id, candidate_prompt="cand", gate_passed=True,
        status=status, evidence={"protected_run_ids": protected}))
    await db.commit()


@pytest.mark.asyncio
async def test_sweep_exempts_protected_replay_run(memdb):
    from server.services import run_redact

    async with memdb() as db:
        spawn = Spawn(name="Bot", domain_category="research", system_prompt="p")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)

        protected_id = await _old_replay_run(db, spawn.id)     # cited by an OPEN proposal
        unref_id = await _old_replay_run(db, spawn.id)          # cited by nobody
        rejected_ref_id = await _old_replay_run(db, spawn.id)   # cited only by a REJECTED proposal
        await _proposal(db, spawn.id, status="open", protected=[protected_id])
        await _proposal(db, spawn.id, status="rejected", protected=[rejected_ref_id])

    redacted = await run_redact.sweep(retention_days=30)

    async with memdb() as db:
        assert (await db.get(Run, protected_id)).system_prompt == "SECRET SYS"  # exempt
        assert (await db.get(Run, unref_id)).system_prompt is None              # redacted
        assert (await db.get(Run, rejected_ref_id)).system_prompt is None       # not exempt
    assert redacted == 2  # only the two non-protected runs were touched
