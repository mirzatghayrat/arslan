"""End-to-end: a route turn writes spawn memory + an arslan summary row, with a stubbed LLM."""
import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, Base, ChatMessage, Spawn


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'smoke.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            s.add(
                Spawn(
                    id=7, name="beauty-guru", domain_category="content-creator",
                    capabilities=["content-generation"], system_prompt="You are a beauty expert.",
                )
            )
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_route_turn_end_to_end(maker, monkeypatch):
    from server.orchestrator import arslan, dispatcher, router

    async def _route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="draft 2 posts")

    monkeypatch.setattr(arslan.router, "route", _route)

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            yield "Post 1. Post 2."

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())

    # Spawn 7 already in roster → route dispatches directly (no invite card).
    from server.services import roster_service
    await roster_service.join("main", 7, via="invited")

    events = []
    await arslan.handle_user_message("main", "make posts", lambda e: events.append(e))

    async with db_session.AsyncSessionLocal() as s:
        cms = (await s.execute(select(ChatMessage))).scalars().all()
        ams = (await s.execute(select(ArslanMessage))).scalars().all()

    # spawn memory got the dispatched exchange; arslan thread got user + spawn_summary
    assert {c.role for c in cms} == {"user", "assistant"}
    roles = [a.role for a in ams]
    assert roles == ["user", "spawn_summary"]
    summary_row = ams[1]
    assert summary_row.display_content == "Post 1. Post 2."        # DISPLAY
    assert "Post 1. Post 2." not in summary_row.content            # MEMORY (1-liner)
