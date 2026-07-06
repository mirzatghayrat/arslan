import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn
from server.registry import service
from server.registry.seeder import seed_registry_with


@pytest.fixture
async def seeded(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as db:
        await seed_registry_with(db)
        s = Spawn(name="S", domain_category="x", system_prompt="p")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_render_chart_universal_even_without_equipment(seeded):
    tools = await service.wired_tools_for_spawn(seeded, current_turn=1)
    keys = {t["key"] for t in tools}
    assert "render_chart" in keys     # available to every spawn with zero equipped toolsets


async def test_web_tools_universal_even_without_equipment(seeded):
    tools = await service.wired_tools_for_spawn(seeded, current_turn=1)
    keys = {t["key"] for t in tools}
    assert {"web_search", "web_extract", "render_chart"} <= keys   # full safe baseline, no equipment needed


async def test_arslan_host_tools_include_render_chart(monkeypatch):
    from server.orchestrator import arslan
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    tools = await arslan._arslan_tools()
    assert {"web_search", "web_extract", "render_chart"} <= {t["key"] for t in tools}
