"""Equipment curation: LLM picks from a safe-only menu; unknown/unsafe keys dropped."""
import anyio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'eq.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_setup)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture
async def seeded(maker):
    from server.registry.seeder import seed_registry

    await seed_registry()
    return maker


class _Resp:
    def __init__(self, content):
        self.content = content


@pytest.mark.asyncio
async def test_curate_validates_and_drops_bad_keys(seeded, monkeypatch):
    from server.services import equipment_service

    captured = {}

    class _A:
        async def chat(self, system, user, **kw):
            captured["system"] = system
            captured["user"] = user
            # model tries to sneak in execution tier + an unknown key
            return _Resp(
                '{"toolsets": ["web_search_scraping", "code_execution", "nope"],'
                ' "skills": ["baoyu-infographic", "claude-code"], "why": "x"}'
            )

    monkeypatch.setattr(equipment_service, "_get_adapter", lambda: _A())

    eq = await equipment_service.curate("小红书美妆内容助手，需要查热点写笔记")
    assert eq["toolsets"] == ["web_search_scraping"]
    assert eq["skills"] == ["baoyu-infographic"]
    # Layer 1: the prompt menu itself must not contain orchestrator items
    assert "code_execution" not in captured["user"]
    assert "terminal" not in captured["user"]
    assert "claude-code" not in captured["user"]


@pytest.mark.asyncio
async def test_curate_llm_failure_falls_back_to_core(seeded, monkeypatch):
    from server.services import equipment_service

    class _A:
        async def chat(self, system, user, **kw):
            return _Resp("not json at all")

    monkeypatch.setattr(equipment_service, "_get_adapter", lambda: _A())

    eq = await equipment_service.curate("anything")
    assert eq["toolsets"] == ["web_search_scraping"]  # deterministic fallback
    assert eq["skills"] == []


@pytest.mark.asyncio
async def test_build_intro_grounded_in_equipment(seeded, maker):
    from server.services import equipment_service

    intro = await equipment_service.build_intro(
        name="小美",
        persona_role="你的小红书美妆助手",
        equipment={"toolsets": [{"key": "web_search_scraping",
                                 "name": "Web Search & Scraping", "status": "wired"}],
                   "skills": [{"key": "baoyu-infographic",
                               "name": "baoyu-infographic", "status": "registered"}]},
    )
    assert "小美" in intro
    assert "Web Search & Scraping" in intro
    assert "baoyu-infographic" in intro
