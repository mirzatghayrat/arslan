import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arslan.models import LLMResponse
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


async def test_compress_stores_compressed(memdb, monkeypatch):
    sid = await _spawn(memdb)
    class _A:
        async def chat(self, system, user):
            return LLMResponse(content="CLEAN SUBSTANTIVE TEXT", usage={})
    async def fake_build(role=None):
        return _A()
    monkeypatch.setattr(ingest, "build_adapter", fake_build)

    await ingest.ingest_text(sid, "doc", "raw boilerplate nav ads ... real content", compress=True)
    async with memdb() as db:
        rows = (await db.execute(select(KnowledgeChunk.text)
                                 .where(KnowledgeChunk.spawn_id == sid))).scalars().all()
    joined = "\n".join(rows)
    assert "CLEAN SUBSTANTIVE TEXT" in joined
    assert "boilerplate nav ads" not in joined


async def test_compress_failure_uses_original(memdb, monkeypatch):
    sid = await _spawn(memdb)
    class _A:
        async def chat(self, system, user):
            raise RuntimeError("llm down")
    async def fake_build(role=None):
        return _A()
    monkeypatch.setattr(ingest, "build_adapter", fake_build)

    await ingest.ingest_text(sid, "doc", "original raw text", compress=True)
    async with memdb() as db:
        rows = (await db.execute(select(KnowledgeChunk.text)
                                 .where(KnowledgeChunk.spawn_id == sid))).scalars().all()
    assert any("original raw text" in t for t in rows)


async def test_no_compress_by_default(memdb, monkeypatch):
    sid = await _spawn(memdb)
    async def fake_build(role=None):
        raise AssertionError("should not build adapter when compress=False")
    monkeypatch.setattr(ingest, "build_adapter", fake_build)
    await ingest.ingest_text(sid, "doc", "plain text no compression")  # compress defaults False
    async with memdb() as db:
        rows = (await db.execute(select(KnowledgeChunk.text)
                                 .where(KnowledgeChunk.spawn_id == sid))).scalars().all()
    assert any("plain text no compression" in t for t in rows)
