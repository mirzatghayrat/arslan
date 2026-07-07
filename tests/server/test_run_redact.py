import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def test_redact_run_clears_sensitive_keeps_stats(memdb):
    from server.services import run_redact
    from server.db.models import Run, RunStep

    async with memdb() as db:
        run = Run(conversation_id="c", user_message="m", started_at=datetime.datetime.utcnow(),
                  status="scored", overall_score=8.0, total_ms=1234,
                  system_prompt="SECRET SYS", injected_kb="SECRET KB")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        rid = run.id
        db.add(RunStep(run_id=rid, seq=0, kind="tool_call",
                       ref={"tool": "web_search", "ok": True},
                       detail={"args_summary": "q", "summary": "5 results",
                               "args_full": "FULLARGS", "result_raw": "RAWDATA"}))
        await db.commit()

    await run_redact.redact_run(rid)

    async with memdb() as db:
        r = await db.get(Run, rid)
        assert r.system_prompt is None and r.injected_kb is None      # sensitive cleared
        assert r.overall_score == 8.0 and r.total_ms == 1234          # stats kept
        step = (await db.execute(select(RunStep).where(RunStep.run_id == rid))).scalars().first()
        assert "args_full" not in step.detail and "result_raw" not in step.detail  # bulky cleared
        assert step.detail["args_summary"] == "q" and step.detail["summary"] == "5 results"  # summaries kept

    await run_redact.redact_run(rid)  # idempotent — must not raise


async def test_sweep_only_old_runs(memdb):
    from server.services import run_redact
    from server.db.models import Run

    old = datetime.datetime.utcnow() - datetime.timedelta(days=40)
    async with memdb() as db:
        r_old = Run(conversation_id="c", user_message="m", started_at=old, created_at=old,
                    status="scored", system_prompt="OLD")
        r_new = Run(conversation_id="c", user_message="m", started_at=datetime.datetime.utcnow(),
                    status="scored", system_prompt="NEW")
        db.add_all([r_old, r_new])
        await db.commit()
        old_id, new_id = r_old.id, r_new.id

    n = await run_redact.sweep(retention_days=30)

    async with memdb() as db:
        assert (await db.get(Run, old_id)).system_prompt is None   # old redacted
        assert (await db.get(Run, new_id)).system_prompt == "NEW"  # recent kept
    assert n >= 1


async def test_sweep_disabled_when_zero(memdb):
    from server.services import run_redact
    assert await run_redact.sweep(retention_days=0) == 0
