import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import ArslanMessage, Base, Run, RunEvaluation
from server.services import replay_set


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _add_run(Session, *, spawn_id, status, user_message, output, overall, with_eval=True):
    async with Session() as db:
        # E2: the corpus is live epoch>=1 runs only (what the recorder now writes).
        run = Run(conversation_id="c", spawn_id=spawn_id, spawn_name="X",
                  user_message=user_message, status=status, task_tokens=0,
                  overall_score=overall, kind="live", epoch=1)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        if output is not None:
            db.add(ArslanMessage(conversation_id="c", role="spawn_summary",
                                 content="s", display_content=output, run_id=run.id))
        if with_eval:
            db.add(RunEvaluation(run_id=run.id, dimension="fabrication", status="pass",
                                 score=8.0, comment="x"))
            db.add(RunEvaluation(run_id=run.id, dimension="identity", status="pass",
                                 score=9.0, comment="x"))
            db.add(RunEvaluation(run_id=run.id, dimension="completion", status="warn",
                                 score=6.0, comment="x"))
            # a routing eval must be ignored by replay_set
            db.add(RunEvaluation(run_id=run.id, dimension="routing", status="pass",
                                 score=10.0, comment="x"))
        await db.commit()
        return run.id


async def test_build_returns_scored_items(memdb):
    rid = await _add_run(memdb, spawn_id=1, status="scored",
                         user_message="写文案", output="成品文案", overall=7.5)
    items = await replay_set.build(1)
    assert len(items) == 1
    it = items[0]
    assert it["run_id"] == rid
    assert it["task"] == "写文案"
    assert it["baseline_output"] == "成品文案"
    assert it["baseline_overall"] == 7.5
    assert set(it["baseline_dims"]) == {"fabrication", "identity", "completion"}  # no routing
    assert it["baseline_dims"]["completion"] == {"status": "warn", "score": 6.0}


async def test_only_scored_and_cap_and_order(memdb):
    await _add_run(memdb, spawn_id=1, status="recorded", user_message="r", output="o", overall=None)
    await _add_run(memdb, spawn_id=1, status="scored", user_message="a", output="oa", overall=8)
    b = await _add_run(memdb, spawn_id=1, status="scored", user_message="b", output="ob", overall=9)
    items = await replay_set.build(1, cap=1)
    assert len(items) == 1            # cap respected
    assert items[0]["run_id"] == b    # newest first


async def test_skips_missing_output_and_handles_empty(memdb):
    await _add_run(memdb, spawn_id=2, status="scored", user_message="t", output=None, overall=8)
    await _add_run(memdb, spawn_id=2, status="scored", user_message="t2", output="", overall=8)
    assert await replay_set.build(2) == []   # both skipped → empty
    assert await replay_set.build(999) == []  # no runs → empty

# NOTE (FIX 1): replay_set.build_split (position-based train/val split) was removed — the
# evolution loop now derives train/val from the ReplayGate PROPOSE partition so the optimizer
# can never train on a certifying holdout task. Its two split tests were removed with it.
