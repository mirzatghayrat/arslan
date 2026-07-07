"""Growth-event capture wired into the orchestrator hot path (Task 2 of the
conversation-recap plan): memory (save_facts), distill (dual-track), invite.
Uses the same maker/MockAdapter harness as tests/server/test_gather_gate.py."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ConversationEvent, Spawn
from tests.server.conftest import MockAdapter


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'recap_capture.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            s.add(
                Spawn(
                    id=7,
                    name="beauty-guru",
                    domain_category="content-creator",
                    capabilities=["content-generation"],
                    system_prompt="You are a beauty expert.",
                )
            )
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _events(collector):
    return lambda ev: collector.append(ev)


@pytest.mark.asyncio
async def test_memory_event_logged_on_facts(maker, monkeypatch):
    """A route decision carrying new_facts must, after save_facts persists them,
    log a `memory` growth event for this conversation."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="answer",
            new_facts=[{"content": "领域兴趣: 半导体", "sensitive": False}],
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    adapter = MockAdapter(stream_chunks=["ok"], chat_content="ok")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    await arslan.handle_user_message("main", "我对半导体很感兴趣", _events(events))

    from sqlalchemy import select

    async with maker() as db:
        rows = (
            await db.execute(
                select(ConversationEvent).where(ConversationEvent.conversation_id == "main")
            )
        ).scalars().all()
    assert any(r.kind == "memory" for r in rows)
    memory_rows = [r for r in rows if r.kind == "memory"]
    assert "半导体" in memory_rows[0].summary


@pytest.mark.asyncio
async def test_no_memory_event_without_facts(maker, monkeypatch):
    """No new_facts → no memory event (guards against over-logging every turn)."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    adapter = MockAdapter(stream_chunks=["ok"], chat_content="ok")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    await arslan.handle_user_message("main2", "hello", _events(events))

    from sqlalchemy import select

    async with maker() as db:
        rows = (
            await db.execute(
                select(ConversationEvent).where(ConversationEvent.conversation_id == "main2")
            )
        ).scalars().all()
    assert not any(r.kind == "memory" for r in rows)
