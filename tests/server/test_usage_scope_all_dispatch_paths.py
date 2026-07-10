"""S0 hemostasis: token/model capture must work for EVERY dispatch path, not only
typed-message turns. Previously `usage_sink.collecting()` wrapped only
`handle_user_message`, so dispatches entered via other WS actions
(route_to / redo / refine / confirm_direction / roster_invite accept /
confirm_create's initial run) ran with NO active usage sink → the Run was recorded
with model=None, provider=None, task_tokens=0, tokens_estimated=True.

The structural fix moves the `usage_sink.collecting()` boundary INTO `_dispatch_spawn`
(the single choke point every Run-recording path funnels through), one scope per Run.
This ALSO fixes the audited turn-cumulative double-count: each Run reads its own fresh
bucket instead of a turn-wide one shared across auto-continue re-dispatches.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.llm import usage_sink
from server.db import session as db_session
from server.db.models import Base, Run, Spawn
from server.orchestrator import arslan, dispatcher, router
from server.services import roster_service, run_recorder


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


def _reporting_dispatch(usage_by_call):
    """Build a fake dispatcher.dispatch that simulates the adapter choke point reporting
    real usage into the ACTIVE usage_sink, then returns a spawn deliverable. Each call
    consumes the next (tokens_in, tokens_out, total, full_output) tuple from usage_by_call.
    """
    from server.orchestrator import memory as _memory

    state = {"i": 0}

    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, on_chunk=None,
                            on_event=None, prior_output=None, instruction=None,
                            allow_escalation=True, mode="execute", attached_context=None,
                            run_id=None):
        tin, tout, total, out = usage_by_call[min(state["i"], len(usage_by_call) - 1)]
        state["i"] += 1
        # Mirror LLMAdapter's choke point: report structured detail + a total token count.
        usage_sink.report_detail(tokens_in=tin, tokens_out=tout,
                                 model="claude-x", provider="anthropic")
        usage_sink.report(total)
        if on_chunk:
            on_chunk("done")
        sid = await _memory.add_message(
            conversation_id, "spawn_summary", out, display_content=out, spawn_id=spawn_id)
        return {"full_output": out, "spawn_name": "Mermer",
                "summary_message_id": sid, "assistant_message_id": 1, "escalation": None}

    return fake_dispatch, state


async def test_non_typed_dispatch_captures_model_and_tokens(memdb, monkeypatch):
    """A dispatch entered via a NON-typed WS action (here `dispatch_routed`, the shared path
    used by route_to / redo / refine / roster_invite accept) must record a real model +
    provider + non-zero tokens on its finalized Run. On the pre-fix code this Run comes back
    model=None / task_tokens=0 because no usage_sink scope is active outside handle_user_message.
    """
    spawn_id = await _seed_spawn(memdb)
    fake_dispatch, _ = _reporting_dispatch([(120, 80, 200, "delivered")])
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)
    await roster_service.join("c1", spawn_id, via="invited")

    events = []
    # Enter via dispatch_routed directly — no surrounding handle_user_message /
    # usage_sink.collecting() scope, exactly like the WS route_to/redo/refine handlers.
    await arslan.dispatch_routed("c1", spawn_id, "do it", False, events.append)

    async with memdb() as db:
        run = (await db.execute(select(Run))).scalars().one()

    assert run.model == "claude-x"
    assert run.provider == "anthropic"
    assert run.task_tokens == 200
    assert run.tokens_in == 120
    assert run.tokens_out == 80
    assert run.tokens_estimated is False


async def test_auto_continue_runs_do_not_double_count(memdb, monkeypatch):
    """A single user turn that auto-continues produces TWO Runs. Each Run must carry ONLY its
    own usage — the second Run's task_tokens/tokens_in/tokens_out must NOT include the first
    Run's (the audited turn-cumulative double-count). Round 1 ends with a findings digest
    (triggers exactly one auto-continue); round 2 has no digest and stops.
    """
    spawn_id = await _seed_spawn(memdb)

    async def fake_route(conversation_id, user_message):
        return router.RouterResult(action="route", spawn_id=spawn_id,
                                   task_brief="do it", new_facts=[])
    monkeypatch.setattr(router, "route", fake_route)

    fake_dispatch, state = _reporting_dispatch([
        (100, 50, 150, "round 1\n\n【阶段性发现】progress made"),  # digest → auto-continue
        (30, 20, 50, "round 2 final answer"),                       # no digest → stop
    ])
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)
    await roster_service.join("c1", spawn_id, via="invited")

    events = []
    # Typed path (the ONE path that historically had a scope) — names Mermer so the
    # doer-first divert is skipped and the route dispatches directly.
    await arslan.handle_user_message("c1", "让Mermer查一下", events.append)

    assert state["i"] == 2  # exactly two dispatches (one auto-continue)

    async with memdb() as db:
        runs = (await db.execute(select(Run).order_by(Run.id))).scalars().all()

    assert len(runs) == 2
    # Run 1: its own usage.
    assert runs[0].task_tokens == 150
    assert runs[0].tokens_in == 100
    assert runs[0].tokens_out == 50
    # Run 2: ONLY its own usage — not 200 / 130 / 70 (cumulative bleed).
    assert runs[1].task_tokens == 50
    assert runs[1].tokens_in == 30
    assert runs[1].tokens_out == 20
    assert runs[0].model == "claude-x" and runs[1].model == "claude-x"
