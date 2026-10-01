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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.llm import usage_sink
from server.db import session as db_session
from server.db.models import Base, Spawn
from server.services import run_recorder


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
                            allow_escalation=True, mode="execute", attached_context=None, images=None,
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




