"""End-to-end: a seeded skill's backfilled body reaches the spawn prompt (P3-3 injection)."""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, SpawnCapability


async def test_seeded_skill_body_reaches_spawn(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'e.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from server.orchestrator.dispatcher import build_spawn_system
    from server.registry.seeder import seed_registry_with
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as db:
        await seed_registry_with(db)
        db.add(Spawn(id=5, name="Debugger", domain_category="software-development", system_prompt="sp"))
        db.add(SpawnCapability(spawn_id=5, kind="skill", ref_key="systematic-debugging"))
        await db.commit()
        spawn = await db.get(Spawn, 5)
    system, _ = await build_spawn_system(spawn, retrieval_query="bug", current_turn=1)

    assert "Your techniques" in system            # P3-3 body-injection section
    assert "决策规则" in system                     # the authored body landed in the prompt
