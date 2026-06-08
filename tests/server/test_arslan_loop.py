"""Orchestration loop: answer / route / suggest_create + fact saving."""
import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, Base, Spawn, UserFact


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'loop.db'}")
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
async def test_answer_path_streams_and_persists(maker, monkeypatch):
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer", new_facts=[{"content": "likes brevity"}])

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    async def _fake_answer_stream(system, user, history=None):
        for piece in ["Hi ", "there"]:
            yield piece

    monkeypatch.setattr(arslan, "_answer_stream", _fake_answer_stream)

    events = []
    await arslan.handle_user_message("main", "hello", _events(events))

    types = [e["type"] for e in events]
    assert "stream_start" in types and "stream_end" in types
    assert any(e["type"] == "fact_saved" and "brevity" in e["content"] for e in events)

    async with db_session.AsyncSessionLocal() as s:
        ams = (await s.execute(select(ArslanMessage).order_by(ArslanMessage.id))).scalars().all()
        facts = (await s.execute(select(UserFact))).scalars().all()
    assert [a.role for a in ams] == ["user", "arslan"]
    assert ams[1].content == "Hi there"
    assert len(facts) == 1


@pytest.mark.asyncio
async def test_route_path_emits_routing_and_dispatches(maker, monkeypatch):
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="draft posts")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    async def _fake_dispatch(conv, *, spawn_id, task_brief, on_chunk=None):
        for piece in ["P1", "P2"]:
            if on_chunk:
                on_chunk(piece)
        return {"full_output": "P1P2", "spawn_name": "beauty-guru", "summary_message_id": 9}

    monkeypatch.setattr(arslan.dispatcher, "dispatch", _fake_dispatch)

    events = []
    await arslan.handle_user_message("main", "make posts", _events(events))
    types = [e["type"] for e in events]
    assert types[0] == "routing"
    # spawn name resolved (via dispatcher.get_spawn_name against the seeded spawn 7) before streaming
    assert events[0]["spawn_name"] == "beauty-guru"
    assert "stream_start" in types and "stream_end" in types


@pytest.mark.asyncio
async def test_suggest_create_emits_card(maker, monkeypatch):
    from server.orchestrator import arslan, router

    draft = {"name": "translator", "domain": "personal-assistant.translator"}

    async def _fake_route(conv, msg):
        return router.RouterResult(action="suggest_create", suggested_spawn=draft)

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    events = []
    await arslan.handle_user_message("main", "translate things often", _events(events))
    assert any(e["type"] == "suggest_create" and e["draft"] == draft for e in events)
