import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, Run, RunStep, Spawn
from server.orchestrator import arslan, dispatcher, router, run_trace
from server.services import run_recorder, roster_service
from arslan.llm import usage_sink


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

    # Spawn already in roster → route dispatches directly (no invite card). The
    # message NAMES Mermer so the doer-first explicit-naming gate (arslan.py
    # _user_named_spawn) honors the direct delegation instead of diverting to
    # Arslan answering the task itself.
    await roster_service.join("c1", spawn_id, via="invited")

    events = []
    await arslan.handle_user_message("c1", "让Mermer查一下", events.append)

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


async def test_dispatch_records_system_prompt_and_estimated_tokens(memdb, monkeypatch):
    """_dispatch_spawn wraps dispatch in run_trace.collecting() so a prompt recorded by
    build_spawn_system (simulated here the way the real dispatcher does it) survives to
    finalize(), and streaming-spawn output with no real usage_sink report is labeled
    tokens_estimated=True."""
    spawn_id = await _seed_spawn(memdb)

    async def fake_route(conversation_id, user_message):
        return router.RouterResult(action="route", spawn_id=spawn_id,
                                   task_brief="do it", new_facts=[])
    monkeypatch.setattr(router, "route", fake_route)

    from server.orchestrator import memory as _memory

    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, on_chunk=None,
                            on_event=None, prior_output=None, instruction=None,
                            allow_escalation=True, mode="execute", attached_context=None):
        # Mirrors what the real dispatcher.build_spawn_system does mid-dispatch.
        run_trace.record_prompt(system_prompt="SYSTEM PROMPT FOR SPAWN", injected_kb=None)
        if on_chunk:
            on_chunk("done")
        sid = await _memory.add_message(
            conversation_id, "spawn_summary", "[Mermer] do it -> delivered",
            display_content="done", spawn_id=spawn_id)
        return {"full_output": "done", "spawn_name": "Mermer",
                "summary_message_id": sid, "assistant_message_id": 1, "escalation": None}
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)

    await roster_service.join("c1", spawn_id, via="invited")

    events = []
    await arslan.handle_user_message("c1", "让Mermer查一下", events.append)

    async with memdb() as db:
        run = (await db.execute(select(Run))).scalars().one()
        assert run.system_prompt == "SYSTEM PROMPT FOR SPAWN"
        assert run.tokens_estimated is True
        assert run.error_kind is None


async def test_dispatch_exception_path_records_error_kind_and_text(memdb, monkeypatch):
    """When dispatch() raises, finalize must capture error_kind/error_text (and still
    run inside the run_trace context without blowing up)."""
    spawn_id = await _seed_spawn(memdb)

    async def fake_route(conversation_id, user_message):
        return router.RouterResult(action="route", spawn_id=spawn_id,
                                   task_brief="do it", new_facts=[])
    monkeypatch.setattr(router, "route", fake_route)

    async def failing_dispatch(conversation_id, *, spawn_id, task_brief, on_chunk=None,
                               on_event=None, prior_output=None, instruction=None,
                               allow_escalation=True, mode="execute", attached_context=None):
        raise RuntimeError("boom-explosion")
    monkeypatch.setattr(dispatcher, "dispatch", failing_dispatch)

    await roster_service.join("c1", spawn_id, via="invited")

    events = []
    await arslan.handle_user_message("c1", "让Mermer查一下", events.append)

    async with memdb() as db:
        run = (await db.execute(select(Run))).scalars().one()
        assert run.error_kind == "RuntimeError"
        assert run.error_text == "boom-explosion"
        assert run.status == "recorded"

    error_events = [e for e in events if e.get("type") == "error"]
    assert error_events and error_events[0]["code"] == "SPAWN_ERROR"
