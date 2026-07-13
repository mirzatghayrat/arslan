"""Task B2: the emitted suggest_create draft carries real equipment + gaps.

The router's RouterResult.suggested_spawn lacks equipment fields. The orchestration
loop (server/orchestrator/arslan.py) enriches the draft via equipment_service.curate
(the same L1 mapping) best-effort before emitting the suggest_create frame.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


async def _ready_slots(history_text):
    """Drive the staffing spine's ready path so the suggest_create card emits."""
    return {"domain": "x.y", "capability": "do-x", "first_task": "run x", "recurrence": True}


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'equip.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_suggest_create_draft_carries_equipment(maker, monkeypatch):
    from server.orchestrator import arslan, router

    draft = {
        "name": "serp-analyst",
        "domain": "marketing.seo",
        "capabilities": ["seo-research"],
        "persona_role": "SEO analyst",
    }

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn=draft,
            task_brief="analyze SERP for keyword X",
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    async def fake_curate(need):
        assert need and need.strip()
        return {
            "toolsets": ["web_search_scraping"],
            "skills": ["statistical-analysis"],
            "mcps": [],
            "gaps": ["real-time SERP data"],
        }

    monkeypatch.setattr(arslan.equipment_service, "curate", fake_curate)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _ready_slots)

    events = []
    await arslan.handle_user_message("main", "I need SERP analysis often", lambda ev: events.append(ev))

    sc = next(e for e in events if e["type"] == "suggest_create")
    enriched = sc["draft"]
    assert enriched["tools"] == ["web_search_scraping"]
    assert enriched["skills"] == ["statistical-analysis"]
    assert enriched["mcps"] == []
    assert enriched["gaps"] == ["real-time SERP data"]


@pytest.mark.asyncio
async def test_suggest_create_enrichment_best_effort_on_curate_failure(maker, monkeypatch):
    """If curate raises, the suggestion still emits with empty equipment lists."""
    from server.orchestrator import arslan, router

    draft = {
        "name": "translator",
        "domain": "personal-assistant.translator",
        "capabilities": ["translation"],
    }

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create", suggested_spawn=draft, task_brief="translate this doc"
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    async def boom(need):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(arslan.equipment_service, "curate", boom)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _ready_slots)

    events = []
    await arslan.handle_user_message("main", "translate things", lambda ev: events.append(ev))

    sc = next(e for e in events if e["type"] == "suggest_create")
    enriched = sc["draft"]
    assert enriched["tools"] == []
    assert enriched["skills"] == []
    assert enriched["mcps"] == []
    assert enriched["gaps"] == []
