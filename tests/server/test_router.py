"""Router: JSON parsing, validation, fallback, audit log."""
import json

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, RouterDecision, Spawn


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'r.db'}")
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
                    domain_subcategory="xiaohongshu",
                    capabilities=["content-generation"],
                    system_prompt="You are a beauty expert.",
                )
            )
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _stub_adapter(content: str):
    class _A:
        provider_name = "openai"
        model = "gpt-4o"

        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            from arslan.models import LLMResponse

            return LLMResponse(content=content, usage={})

    return _A()


@pytest.mark.asyncio
async def test_router_parses_route_decision(maker, monkeypatch):
    from server.orchestrator import router

    raw = '```json\n{"action":"route","spawn_id":7,"task_brief":"draft posts","reason":"x"}\n```'
    monkeypatch.setattr(router, "_get_adapter", lambda: _stub_adapter(raw))

    result = await router.route("main", "make me xiaohongshu posts")
    assert result.action == "route"
    assert result.spawn_id == 7
    assert result.task_brief == "draft posts"

    async with db_session.AsyncSessionLocal() as s:
        dec = (await s.execute(select(RouterDecision))).scalar_one()
    assert dec.action == "route" and dec.spawn_id == 7


@pytest.mark.asyncio
async def test_router_extracts_new_facts(maker, monkeypatch):
    from server.orchestrator import router

    raw = '{"action":"answer","new_facts":[{"content":"likes data-driven tone","sensitive":false}]}'
    monkeypatch.setattr(router, "_get_adapter", lambda: _stub_adapter(raw))
    result = await router.route("main", "I like data-driven content")
    assert result.action == "answer"
    assert result.new_facts == [{"content": "likes data-driven tone", "sensitive": False}]


@pytest.mark.asyncio
async def test_router_falls_back_on_bad_json(maker, monkeypatch):
    from server.orchestrator import router

    monkeypatch.setattr(router, "_get_adapter", lambda: _stub_adapter("not json at all"))
    result = await router.route("main", "hello")
    assert result.action == "answer"  # fallback

    async with db_session.AsyncSessionLocal() as s:
        dec = (await s.execute(select(RouterDecision))).scalar_one()
    assert dec.action == "fallback"


@pytest.mark.asyncio
async def test_router_rejects_unknown_action(maker, monkeypatch):
    from server.orchestrator import router

    monkeypatch.setattr(router, "_get_adapter", lambda: _stub_adapter('{"action":"nuke"}'))
    result = await router.route("main", "hello")
    assert result.action == "answer"


@pytest.mark.asyncio
async def test_router_recovers_json_in_prose(maker, monkeypatch):
    from server.orchestrator import router

    monkeypatch.setattr(
        router, "_get_adapter",
        lambda: _stub_adapter('Sure! Here you go: {"action":"answer","reason":"ok"} hope that helps'),
    )
    result = await router.route("main", "hi")
    assert result.action == "answer"


@pytest.mark.asyncio
async def test_router_route_without_spawn_id_downgrades(maker, monkeypatch):
    from server.orchestrator import router
    from sqlalchemy import select
    from server.db.models import RouterDecision

    monkeypatch.setattr(
        router, "_get_adapter", lambda: _stub_adapter('{"action":"route","task_brief":"x"}')
    )
    result = await router.route("main", "do something")
    assert result.action == "answer"  # downgraded (no spawn_id)
    async with db_session.AsyncSessionLocal() as s:
        dec = (await s.execute(select(RouterDecision))).scalar_one()
    assert dec.action == "fallback"


@pytest.mark.asyncio
async def test_router_fallback_stores_raw(maker, monkeypatch):
    from server.orchestrator import router
    from sqlalchemy import select
    from server.db.models import RouterDecision

    monkeypatch.setattr(router, "_get_adapter", lambda: _stub_adapter("totally not json"))
    await router.route("main", "hi")
    async with db_session.AsyncSessionLocal() as s:
        dec = (await s.execute(select(RouterDecision))).scalar_one()
    assert dec.raw == {"_raw": "totally not json"}


@pytest.mark.asyncio
async def test_suggest_create_carries_task_brief_and_overlaps(maker, monkeypatch):
    from server.orchestrator import router

    payload = {
        "action": "suggest_create",
        "suggested_spawn": {
            "name": "equity-researcher", "domain": "finance.equity-research",
            "capabilities": ["research"], "persona_role": "equity analyst", "persona_tone": "rigorous",
        },
        "task_brief": "Analyze TSLA Q3 fundamentals",
        "overlaps": {"spawn_id": 3, "name": "股小助", "axes": ["fundamental vs technical"]},
        "new_facts": [], "reason": "recurring finance research",
    }
    monkeypatch.setattr(router, "_get_adapter", lambda: _stub_adapter(json.dumps(payload)))
    result = await router.route("main", "look at TSLA fundamentals for me")
    assert result.action == "suggest_create"
    assert result.task_brief == "Analyze TSLA Q3 fundamentals"
    assert result.overlaps == {"spawn_id": 3, "name": "股小助", "axes": ["fundamental vs technical"]}


@pytest.mark.asyncio
async def test_router_filters_junk_new_facts(maker, monkeypatch):
    from server.orchestrator import router

    raw = '{"action":"answer","new_facts":["bad string", {"content":"good fact"}, {"content":"  "}]}'
    monkeypatch.setattr(router, "_get_adapter", lambda: _stub_adapter(raw))
    result = await router.route("main", "hi")
    assert result.new_facts == [{"content": "good fact"}]
