"""Gather-before-propose gate: a thin/premature suggest_create must downgrade to clarify."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn
from tests.server.conftest import MockAdapter


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'gate.db'}")
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


async def _fake_curate(need):
    return {"toolsets": [], "skills": [], "mcps": [], "gaps": []}


async def _incomplete_slots(history_text):
    """Slot extraction returning an under-specified need (gate must NOT pass)."""
    return {"domain": None, "capability": None, "first_task": None, "recurrence": None}


async def _ready_slots(history_text):
    """Slot extraction returning a complete need (gate passes → propose)."""
    return {"domain": "marketing.seo", "capability": "seo-audit",
            "first_task": "audit keywords", "recurrence": True}


@pytest.mark.asyncio
async def test_underspecified_create_downgrades_to_clarify(maker, monkeypatch):
    """A bare 'make me a spawn' (no domain/caps/task) must NOT emit suggest_create —
    Arslan clarifies first via the answer path with the clarify addendum."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn={"name": "helper"},  # no domain, no capabilities
            task_brief=None,
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _incomplete_slots)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)

    adapter = MockAdapter(stream_chunks=["What ", "kind?"], chat_content="What kind?")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    await arslan.handle_user_message("main", "make me a spawn", _events(events))
    types = [e["type"] for e in events]

    # No premature proposal
    assert "suggest_create" not in types
    # Instead it clarifies via the answer path
    assert "stream_start" in types and "stream_end" in types
    captured_system = (adapter.chat_stream_calls + adapter.chat_calls)[0]["system"]
    assert "clarifying questions" in captured_system
    assert "under-specified" in captured_system


@pytest.mark.asyncio
async def test_specified_create_proposes(maker, monkeypatch):
    """A sufficiently-specified draft (domain + capability + concrete task) DOES propose."""
    from server.orchestrator import arslan, router

    draft = {
        "name": "seo-auditor",
        "domain": "marketing.seo",
        "capabilities": ["seo-audit"],
        "persona_role": "SEO analyst",
    }

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn=draft,
            task_brief="audit my site's keywords",
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _ready_slots)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)

    events = []
    await arslan.handle_user_message("main", "audit my site", _events(events))
    types = [e["type"] for e in events]
    assert "suggest_create" in types
