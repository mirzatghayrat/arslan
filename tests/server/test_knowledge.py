import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, Collection
from server.db.migrations.versions._0009_knowledge import upgrade_sync
from server.services import ingest, knowledge


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(upgrade_sync)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _collection(Session) -> int:
    """The chunks' home: a collection (an expert's own well has no model since C7c-5b)."""
    async with Session() as db:
        c = Collection(name="S")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def test_retrieve_empty_and_weird_query_no_crash(memdb):
    cid = await _collection(memdb)
    assert await knowledge.retrieve_scoped("", spawn_id=None) == []
    await ingest.ingest_text(None, "doc", "hello world", collection_id=cid)
    assert isinstance(await knowledge.retrieve_scoped('"*(quote) AND foo*', spawn_id=None), list)


def test_knowledge_block_format():
    assert knowledge.knowledge_block([]) == ""
    block = knowledge.knowledge_block([("src.txt", "chunk one"), ("src.txt", "chunk two")])
    assert "knowledge base" in block.lower()
    assert "chunk one" in block and "chunk two" in block
    assert "[src.txt]" in block
