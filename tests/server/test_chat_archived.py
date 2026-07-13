from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session_mod
from server.db.models import Base, ChatMessage, Spawn


async def test_chat_message_archived_defaults_false(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'c.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as s:
        s.add(Spawn(id=1, name="x", domain_category="t", system_prompt="sp"))
        s.add(ChatMessage(spawn_id=1, role="user", content="hi"))
        await s.commit()
        row = (await s.execute(select(ChatMessage))).scalars().one()
        assert row.archived is False


async def test_history_excludes_archived(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'h.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as s:
        s.add(Spawn(id=1, name="x", domain_category="t", system_prompt="sp"))
        s.add(ChatMessage(spawn_id=1, role="user", content="old", archived=True))
        s.add(ChatMessage(spawn_id=1, role="user", content="new", archived=False))
        await s.commit()
    monkeypatch.setattr(db_session_mod, "AsyncSessionLocal", maker)
    from server.ws import chat as chat_mod
    rows = await chat_mod._history(1)
    contents = [r.content for r in rows]
    assert contents == ["new"]
