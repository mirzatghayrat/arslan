import pytest
from sqlalchemy import select
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


async def test_ingest_url_uses_web_extract_executor(memdb, monkeypatch):
    sid = await _spawn(memdb)
    from server.registry import executors
    calls = {}
    class _Stub:
        async def execute(self, args):
            calls["url"] = args["url"]
            return {"ok": True, "url": args["url"], "text": "extracted page body about pricing"}
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Stub())

    n = await ingest.ingest_url(sid, "https://example.com/pricing")
    assert n >= 1
    assert calls["url"] == "https://example.com/pricing"
    async with memdb() as db:
        rows = (await db.execute(select(KnowledgeChunk.text)
                                 .where(KnowledgeChunk.spawn_id == sid))).scalars().all()
    assert any("pricing" in t for t in rows)


async def test_ingest_url_private_rejected(memdb, monkeypatch):
    sid = await _spawn(memdb)
    from server.registry import executors
    class _Stub:
        async def execute(self, args):
            return {"ok": False, "error": "url resolves to a private or internal address"}
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Stub())

    with pytest.raises(ValueError):
        await ingest.ingest_url(sid, "http://169.254.169.254/latest/meta-data/")
    async with memdb() as db:
        rows = (await db.execute(select(KnowledgeChunk).where(KnowledgeChunk.spawn_id == sid))).scalars().all()
    assert rows == []   # nothing ingested


async def test_ingest_url_passes_compress(memdb, monkeypatch):
    sid = await _spawn(memdb)
    from server.registry import executors
    class _Stub:
        async def execute(self, args):
            return {"ok": True, "url": args["url"], "text": "body content here"}
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Stub())
    seen = {}
    async def fake_ingest_text(spawn_id, source, text, *, compress=False):
        seen["compress"] = compress
        return 1
    monkeypatch.setattr(ingest, "ingest_text", fake_ingest_text)
    await ingest.ingest_url(sid, "https://x.com", compress=True)
    assert seen["compress"] is True
