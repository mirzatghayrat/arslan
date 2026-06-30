import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, Run, RunStep, Spawn
from server.orchestrator import arslan, dispatcher, router
from server.services import run_recorder, roster_service


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda run_id: None)
    yield Session


async def _seed_spawn(Session) -> int:
    async with Session() as db:
        s = Spawn(name="Mermer", domain_category="research", system_prompt="You research.")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_routed_turn_creates_run_with_steps(memdb, monkeypatch):
    spawn_id = await _seed_spawn(memdb)

    async def fake_route(conversation_id, user_message):
        return router.RouterResult(action="route", spawn_id=spawn_id,
                                   task_brief="do it", new_facts=[])
    monkeypatch.setattr(router, "route", fake_route)

    from server.orchestrator import memory as _memory

    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, on_chunk=None,
                            on_event=None, prior_output=None, instruction=None,
                            allow_escalation=True, mode="execute", attached_context=None):
        if on_chunk:
            on_chunk("done")
        sid = await _memory.add_message(
            conversation_id, "spawn_summary", "[Mermer] do it -> delivered",
            display_content="done", spawn_id=spawn_id)
        return {"full_output": "done", "spawn_name": "Mermer",
                "summary_message_id": sid, "assistant_message_id": 1, "escalation": None}
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)

    # Spawn already in roster → route dispatches directly (no invite card).
    await roster_service.join("c1", spawn_id, via="invited")

    events = []
    await arslan.handle_user_message("c1", "查一下", events.append)

    async with memdb() as db:
        runs = (await db.execute(select(Run))).scalars().all()
        assert len(runs) == 1
        run = runs[0]
        assert run.status == "recorded"
        assert run.spawn_name == "Mermer"
        steps = (await db.execute(
            select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.seq)
        )).scalars().all()
        assert "route" in [s.kind for s in steps]
        assert "dispatch" in [s.kind for s in steps]

    spawn_meta = [e for e in events if e.get("type") == "spawn_meta"][0]
    assert spawn_meta["run_id"] == run.id
