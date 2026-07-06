import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, KnowledgeChunk, Spawn
from server.db.migrations.versions._0009_knowledge import upgrade_sync
from server.services import ingest


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(upgrade_sync)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


async def _spawn(Session) -> int:
    async with Session() as db:
        s = Spawn(name="S", domain_category="x", system_prompt="p")
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s.id


async def test_ingest_text_stores_chunks(memdb):
    sid = await _spawn(memdb)
    n = await ingest.ingest_text(sid, "doc1", "alpha beta. " * 200)
    assert n >= 1
    async with memdb() as db:
        cnt = (await db.execute(select(func.count()).select_from(KnowledgeChunk)
                                .where(KnowledgeChunk.spawn_id == sid))).scalar_one()
    assert cnt == n


async def test_ingest_strips_private(memdb):
    sid = await _spawn(memdb)
    await ingest.ingest_text(sid, "doc", "public stuff <private>SECRET TOKEN</private> more public")
    async with memdb() as db:
        rows = (await db.execute(select(KnowledgeChunk.text)
                                 .where(KnowledgeChunk.spawn_id == sid))).scalars().all()
    joined = "\n".join(rows)
    assert "SECRET TOKEN" not in joined
    assert "public stuff" in joined


async def test_ingest_file_txt(memdb):
    sid = await _spawn(memdb)
    n = await ingest.ingest_file(sid, "notes.txt", "hello knowledge base".encode("utf-8"))
    assert n == 1


async def test_ingest_file_unknown_ext_raises(memdb):
    sid = await _spawn(memdb)
    with pytest.raises(ValueError):
        await ingest.ingest_file(sid, "archive.zip", b"PK\x03\x04")


async def test_ingest_survives_orphan_fts_rowid(memdb):
    """A stale FTS row (rowid=1) left from a deleted chunk must not make the next
    ingest 500 with a rowid collision — knowledge_chunks ids restart at 1 when the
    table is empty, so ingest overwrites the orphan instead of colliding."""
    from sqlalchemy import text as sa_text
    async with memdb() as db:
        await db.execute(sa_text(
            "INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (1, 'orphan leftover')"))
        await db.commit()
    sid = await _spawn(memdb)
    n = await ingest.ingest_text(sid, "doc", "gamma delta. " * 200)  # first chunk reuses rowid 1
    assert n >= 1
    async with memdb() as db:
        fts = (await db.execute(sa_text(
            "SELECT text FROM knowledge_chunks_fts WHERE rowid = 1"))).scalar_one()
    assert "orphan" not in fts  # FTS now mirrors the real chunk, not the stale row
