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
        run = Run(conversation_id="c", spawn_id=spawn_id, spawn_name="X",
                  user_message=user_message, status=status, task_tokens=0,
                  overall_score=overall)
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
    a = await _add_run(memdb, spawn_id=1, status="scored", user_message="a", output="oa", overall=8)
    b = await _add_run(memdb, spawn_id=1, status="scored", user_message="b", output="ob", overall=9)
    items = await replay_set.build(1, cap=1)
    assert len(items) == 1            # cap respected
    assert items[0]["run_id"] == b    # newest first


async def test_skips_missing_output_and_handles_empty(memdb):
    await _add_run(memdb, spawn_id=2, status="scored", user_message="t", output=None, overall=8)
    await _add_run(memdb, spawn_id=2, status="scored", user_message="t2", output="", overall=8)
    assert await replay_set.build(2) == []   # both skipped → empty
    assert await replay_set.build(999) == []  # no runs → empty


import anyio


def test_split_interleaves_and_holds_out(monkeypatch):
    # 6 fake items (ids 6..1, newest first as build returns them)
    fake = [{"run_id": i, "task": f"t{i}", "baseline_output": f"o{i}",
             "baseline_overall": 7, "baseline_dims": {}} for i in (6, 5, 4, 3, 2, 1)]

    async def fake_build(spawn_id, *, cap):
        return fake[:cap]
    monkeypatch.setattr(replay_set, "build", fake_build)

    split = anyio.run(lambda: replay_set.build_split(1, train_cap=4, val_cap=2, min_val=1))
    train_ids = [it["run_id"] for it in split["train"]]
    val_ids = [it["run_id"] for it in split["val"]]
    # deterministic interleave: every 3rd (index 2,5...) -> val; rest -> train
    assert val_ids == [4, 1]
    assert train_ids == [6, 5, 3, 2]
    assert not (set(train_ids) & set(val_ids))  # held out, no overlap


def test_split_insufficient_returns_empty(monkeypatch):
    async def fake_build(spawn_id, *, cap):
        return [{"run_id": 1, "task": "t", "baseline_output": "o",
                 "baseline_overall": 7, "baseline_dims": {}}]
    monkeypatch.setattr(replay_set, "build", fake_build)
    split = anyio.run(lambda: replay_set.build_split(1, train_cap=4, val_cap=2, min_val=3))
    assert split == {"train": [], "val": []}
