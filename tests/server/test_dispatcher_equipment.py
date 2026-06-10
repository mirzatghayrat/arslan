"""Dispatch injects an equipment block; zero-equipment spawns get the no-tools clause."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, SpawnCapability


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'de.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        from server.registry.seeder import seed_registry

        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        await seed_registry()
        async with m() as s:
            s.add(Spawn(id=7, name="小美", domain_category="content",
                        system_prompt="You are a beauty expert."))
            s.add(Spawn(id=8, name="plain", domain_category="other",
                        system_prompt="You are plain."))
            s.add(Spawn(id=9, name="artist", domain_category="creative",
                        system_prompt="You are an image artist."))
            s.add(SpawnCapability(spawn_id=7, kind="toolset", ref_key="web_search_scraping"))
            s.add(SpawnCapability(spawn_id=7, kind="skill", ref_key="baoyu-infographic"))
            s.add(SpawnCapability(spawn_id=9, kind="toolset", ref_key="image_generation"))
            await s.commit()

    anyio.run(_seed)
    return m


@pytest.mark.asyncio
async def test_equipped_spawn_system_lists_equipment(maker, monkeypatch):
    from server.orchestrator import dispatcher

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["system"] = system
            yield "ok"

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())
    await dispatcher.dispatch("main", spawn_id=7, task_brief="do X")
    s = captured["system"]
    assert "web_search" in s and "web_extract" in s
    assert "baoyu-infographic" in s
    assert "NO other tools" in s
    assert "escalate" in s.lower()


@pytest.mark.asyncio
async def test_unequipped_spawn_keeps_legacy_path(maker, monkeypatch):
    from server.orchestrator import dispatcher

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["system"] = system
            yield "ok"

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())
    await dispatcher.dispatch("main", spawn_id=8, task_brief="do Y")
    assert "web_search" not in captured["system"]


@pytest.mark.asyncio
async def test_not_yet_live_toolset_appears_in_system(maker, monkeypatch):
    """Spawn equipped with a registered (not wired) toolset gets '(not yet live)' label."""
    from server.orchestrator import dispatcher

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["system"] = system
            yield "ok"

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())
    await dispatcher.dispatch("main", spawn_id=9, task_brief="draw something")
    s = captured["system"]
    assert "(not yet live)" in s
    assert "Image Generation" in s
