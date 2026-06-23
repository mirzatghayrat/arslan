import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import ArslanMessage, Base, Run, RunEvaluation, RunStep


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s


async def test_run_with_steps_and_eval_persists(db):
    run = Run(conversation_id="c1", spawn_id=None, spawn_name="Mermer",
              user_message="帮我写个东西", status="recording", task_tokens=0)
    db.add(run)
    await db.commit()
    await db.refresh(run)

    db.add(RunStep(run_id=run.id, seq=0, kind="route", ref={"spawn_name": "Mermer"},
                   detail={}, duration_ms=120))
    db.add(RunEvaluation(run_id=run.id, dimension="routing", status="pass",
                         score=9.0, comment="选对了人"))
    msg = ArslanMessage(conversation_id="c1", role="spawn_summary", content="x",
                        display_content="full", run_id=run.id)
    db.add(msg)
    await db.commit()

    assert run.status == "recording"
    assert run.overall_score is None
    assert msg.run_id == run.id
