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
