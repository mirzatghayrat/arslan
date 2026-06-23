import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.models import LLMResponse
from server.db import session as db_session
from server.db.models import ArslanMessage, Base, Run, RunEvaluation, Spawn
from server.services import run_eval_service


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _seed_run(Session) -> int:
    async with Session() as db:
        spawn = Spawn(name="Mermer", domain_category="research", system_prompt="You research.")
        db.add(spawn)
        await db.commit()
        await db.refresh(spawn)
        run = Run(conversation_id="c1", spawn_id=spawn.id, spawn_name="Mermer",
                  user_message="查天气", status="recorded", task_tokens=10)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        db.add(ArslanMessage(conversation_id="c1", role="spawn_summary",
                             content="s", display_content="今天晴", run_id=run.id))
        await db.commit()
        return run.id


_GOOD_VERDICT = (
    '{"dimensions": {'
    '"routing": {"status": "pass", "score": 9, "comment": "选对了人"},'
    '"fabrication": {"status": "pass", "score": 8, "comment": "无编造"},'
    '"identity": {"status": "pass", "score": 10, "comment": "身份一致"},'
    '"completion": {"status": "warn", "score": 6, "comment": "略简略"}},'
    '"overall": {"score": 8, "badge": "good"}}'
)


async def test_score_persists_dimensions_and_overall(memdb, monkeypatch):
    run_id = await _seed_run(memdb)

    class _Adapter:
        async def chat(self, system, user):
            return LLMResponse(content=_GOOD_VERDICT, usage={})

    async def fake_build(role=None):
        return _Adapter()
    monkeypatch.setattr(run_eval_service, "build_adapter", fake_build)

    await run_eval_service.score(run_id)

    async with memdb() as db:
        run = await db.get(Run, run_id)
        dims = (await db.execute(
            select(RunEvaluation).where(RunEvaluation.run_id == run_id)
        )).scalars().all()

    assert run.status == "scored"
    assert run.overall_score == 8
    assert run.overall_badge == "good"
    assert {d.dimension for d in dims} == {"routing", "fabrication", "identity", "completion"}


async def test_score_marks_failed_on_unparseable(memdb, monkeypatch):
    run_id = await _seed_run(memdb)

    class _Adapter:
        async def chat(self, system, user):
            return LLMResponse(content="not json at all", usage={})

    async def fake_build(role=None):
        return _Adapter()
    monkeypatch.setattr(run_eval_service, "build_adapter", fake_build)

    await run_eval_service.score(run_id)

    async with memdb() as db:
        run = await db.get(Run, run_id)
    assert run.status == "score_failed"
