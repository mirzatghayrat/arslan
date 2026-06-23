import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, Spawn
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


async def _spawn(Session, name="S") -> int:
    async with Session() as db:
        s = Spawn(name=name, domain_category="x", system_prompt="p")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_retrieve_matches(memdb):
    sid = await _spawn(memdb)
    await ingest.ingest_text(sid, "doc", "Our refund policy allows returns within 30 days.")
    await ingest.ingest_text(sid, "doc", "The office is open on weekdays.")
    hits = await knowledge.retrieve(sid, "what is the refund policy?")
    assert any("refund" in h for h in hits)


async def test_retrieve_scoped_to_spawn(memdb):
    a = await _spawn(memdb, "A")
    b = await _spawn(memdb, "B")
    await ingest.ingest_text(a, "doc", "alpha secret material")
    hits_b = await knowledge.retrieve(b, "alpha")
    assert hits_b == []


async def test_retrieve_empty_and_weird_query_no_crash(memdb):
    sid = await _spawn(memdb)
    assert await knowledge.retrieve(sid, "") == []
    await ingest.ingest_text(sid, "doc", "hello world")
    assert isinstance(await knowledge.retrieve(sid, '"*(quote) AND foo*'), list)


def test_knowledge_block_format():
    assert knowledge.knowledge_block([]) == ""
    block = knowledge.knowledge_block(["chunk one", "chunk two"])
    assert "knowledge base" in block.lower()
    assert "chunk one" in block and "chunk two" in block
