import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'i.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from server.registry.seeder import seed_registry
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    await seed_registry()
    async with m() as s:
        s.add(Spawn(id=4, name="小美", domain_category="content", system_prompt="sp",
                    memory_facts=["输出更简短", "标注信息来源"]))
        s.add(Spawn(id=5, name="阿强", domain_category="content", system_prompt="sp", memory_facts=[]))
        await s.commit()
    return m


async def test_memory_facts_injected(maker):
    from server.orchestrator.dispatcher import build_spawn_system
    async def _run(sid):
        async with maker() as s:
            spawn = await s.get(Spawn, sid)
        sys, _ = await build_spawn_system(spawn, retrieval_query="x", current_turn=1)
        return sys
    with_prefs = await _run(4)
    without = await _run(5)
    assert "你已学到的偏好" in with_prefs and "输出更简短" in with_prefs
    assert "你已学到的偏好" not in without
