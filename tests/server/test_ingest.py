import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import Base, KnowledgeChunk, Collection
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


async def _collection(Session) -> int:
    """The chunks' home: a collection (an expert's own well has no model since C7c-5b)."""
    async with Session() as db:
        c = Collection(name="S")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def test_ingest_text_stores_chunks(memdb):
    cid = await _collection(memdb)
    n = await ingest.ingest_text(None, "doc1", "alpha beta. " * 200, collection_id=cid)
    assert n >= 1
    async with memdb() as db:
        cnt = (await db.execute(select(func.count()).select_from(KnowledgeChunk)
                                .where(KnowledgeChunk.collection_id == cid))).scalar_one()
    assert cnt == n


async def test_ingest_strips_private(memdb):
    cid = await _collection(memdb)
    await ingest.ingest_text(None, "doc", "public stuff <private>SECRET TOKEN</private> more public", collection_id=cid)
    async with memdb() as db:
        rows = (await db.execute(select(KnowledgeChunk.text)
                                 .where(KnowledgeChunk.collection_id == cid))).scalars().all()
    joined = "\n".join(rows)
    assert "SECRET TOKEN" not in joined
    assert "public stuff" in joined


async def test_ingest_file_txt(memdb):
    cid = await _collection(memdb)
    n = await ingest.ingest_file(None, "notes.txt", "hello knowledge base".encode("utf-8"), collection_id=cid)
    assert n == 1


async def test_ingest_file_unknown_ext_raises(memdb):
    cid = await _collection(memdb)
    with pytest.raises(ValueError):
        await ingest.ingest_file(None, "archive.zip", b"PK\x03\x04", collection_id=cid)


def test_extract_file_html_strips_tags():
    from server.services.ingest import _extract_file
    out = _extract_file("page.html", b"<html><body><h1>Hi</h1><p>world text</p></body></html>")
    assert "Hi" in out and "world text" in out
    assert "<h1>" not in out and "<p>" not in out


def test_extract_file_bad_html_no_raise():
    from server.services.ingest import _extract_file
    assert _extract_file("broken.htm", b"\xff\xfe not really html <<<") is not None  # no exception


async def test_ingest_survives_orphan_fts_rowid(memdb):
    """A stale FTS row (rowid=1) left from a deleted chunk must not make the next
    ingest 500 with a rowid collision — knowledge_chunks ids restart at 1 when the
    table is empty, so ingest overwrites the orphan instead of colliding."""
    from sqlalchemy import text as sa_text
    async with memdb() as db:
        await db.execute(sa_text(
            "INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (1, 'orphan leftover')"))
        await db.commit()
    cid = await _collection(memdb)
    n = await ingest.ingest_text(None, "doc", "gamma delta. " * 200, collection_id=cid)  # first chunk reuses rowid 1
    assert n >= 1
    async with memdb() as db:
        fts = (await db.execute(sa_text(
            "SELECT text FROM knowledge_chunks_fts WHERE rowid = 1"))).scalar_one()
    assert "orphan" not in fts  # FTS now mirrors the real chunk, not the stale row
