"""TDD: ConversationSpawn model — unique constraint on (conversation_id, spawn_id)."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import server.db.session as db_session
from server.db.models import Base, ConversationSpawn


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'cs.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _c():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_c)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_conversation_spawn_unique(maker):
    from sqlalchemy.exc import IntegrityError

    async with maker() as s:
        s.add(ConversationSpawn(conversation_id="c1", spawn_id=4, joined_via="routed"))
        await s.commit()

    async with maker() as s:
        s.add(ConversationSpawn(conversation_id="c1", spawn_id=4, joined_via="invited"))
        with pytest.raises(IntegrityError):
            await s.commit()
