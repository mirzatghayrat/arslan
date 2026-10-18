"""Deleting a spawn with orchestrator-thread references must succeed and
preserve the conversation (spawn_id nulled), and remove equipment rows."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import (
    ArslanMessage, Base, ChatMessage, Spawn, SpawnCapability,
)
from server.services import spawn_service


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'del.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        # Enforce FKs so the test actually reproduces the production failure mode.
        from sqlalchemy import text
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_delete_spawn_with_thread_refs_and_equipment(maker):
    async with maker() as s:
        s.add(Spawn(id=5, name="doomed", domain_category="d", system_prompt="p"))
        await s.commit()
        s.add(ChatMessage(spawn_id=5, role="user", content="hi"))
        s.add(ArslanMessage(conversation_id="main", role="spawn_summary",
                            content="[doomed] task -> delivered", spawn_id=5))
        s.add(SpawnCapability(spawn_id=5, kind="toolset", ref_key="web_search_scraping"))
        await s.commit()

    async with maker() as s:
        ok = await spawn_service.delete_spawn(s, 5)
    assert ok is True

    async with maker() as s:
        assert (await s.get(Spawn, 5)) is None
        # conversation history survives, unlinked
        am = (await s.execute(select(ArslanMessage))).scalar_one()
        assert am.spawn_id is None and "doomed" in am.content
        # spawn-scoped rows are gone
        assert (await s.execute(select(ChatMessage))).scalars().all() == []
        assert (await s.execute(select(SpawnCapability))).scalars().all() == []


# Moved from test_default_spawns.py when C1b deleted default_spawns.py: they test spawn_service,
# which stays. Installs from before 0.1.48 still hold is_default=True rows, and
# DELETE /api/v1/spawns/{id} answers 403 for them (server/api/spawns.py).
def test_to_summary_carries_is_default():
    sp = Spawn(id=1, name="B", domain_category="x", capabilities=[], system_prompt="x", is_default=True)
    assert spawn_service.to_summary(sp).is_default is True


@pytest.mark.asyncio
async def test_delete_rejects_builtin(maker):
    async with maker() as s:
        sp = Spawn(name="Built-In", domain_category="x", capabilities=[], system_prompt="x", is_default=True)
        s.add(sp)
        await s.commit()
        await s.refresh(sp)
        with pytest.raises(spawn_service.BuiltInSpawnError):
            await spawn_service.delete_spawn(s, sp.id)
        assert await s.get(Spawn, sp.id) is not None   # not deleted


@pytest.mark.asyncio
async def test_delete_allows_normal_spawn(maker):
    async with maker() as s:
        sp = Spawn(name="Normal", domain_category="x", capabilities=[], system_prompt="x", is_default=False)
        s.add(sp)
        await s.commit()
        await s.refresh(sp)
        assert await spawn_service.delete_spawn(s, sp.id) is True
