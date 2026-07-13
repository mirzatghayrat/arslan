"""Creating from a draft equips the spawn (validated), persists an intro, and
spawn_created carries equipment."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ChatMessage, SpawnCapability


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ce.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.fixture
async def seeded(maker):
    from server.registry.seeder import seed_registry

    await seed_registry()
    return maker


@pytest.mark.asyncio
async def test_create_from_draft_equips_and_introduces(seeded, maker, monkeypatch):
    from server.services import equipment_service
    from server.ws.arslan import _create_from_draft

    async def _fake_curate(desc):
        return {"toolsets": ["web_search_scraping"], "skills": ["baoyu-infographic"]}

    monkeypatch.setattr(equipment_service, "curate", _fake_curate)

    spawn_id, name, equipment, intro = await _create_from_draft(
        {"name": "小美", "domain": "content.xiaohongshu",
         "capabilities": ["写笔记"], "persona_role": "小红书美妆助手"}
    )
    assert {t["key"] for t in equipment["toolsets"]} == {"web_search_scraping"}
    assert {s["key"] for s in equipment["skills"]} == {"baoyu-infographic"}
    assert "小美" in intro and "Web Search & Scraping" in intro

    async with maker() as s:
        caps = (await s.execute(select(SpawnCapability))).scalars().all()
        assert {(c.kind, c.ref_key) for c in caps} == {
            ("toolset", "web_search_scraping"), ("skill", "baoyu-infographic"),
        }
        # intro persisted as the spawn's first assistant message
        msg = (await s.execute(select(ChatMessage))).scalar_one()
        assert msg.spawn_id == spawn_id and msg.role == "assistant"
        assert msg.content == intro


@pytest.mark.asyncio
async def test_create_explicit_equipment_is_validated(seeded, maker):
    """Caller-supplied equipment (manual create / user edit) hits assert_assignable."""
    from server.registry.service import NotAssignableError
    from server.ws.arslan import _create_from_draft

    with pytest.raises(NotAssignableError):
        await _create_from_draft(
            {"name": "evil", "domain": "x",
             "equipment": {"toolsets": ["code_execution"], "skills": []}}
        )
