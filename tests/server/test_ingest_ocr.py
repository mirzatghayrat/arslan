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


async def test_ocr_fallback_when_no_text_layer(memdb, monkeypatch):
    sid = await _spawn(memdb)
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: "   ")
    monkeypatch.setattr(ingest, "_ocr_pdf", lambda data: "OCR EXTRACTED TEXT from scan")
    n = await ingest.ingest_file(sid, "scan.pdf", b"%PDF-fake")
    assert n >= 1
    async with memdb() as db:
        rows = (await db.execute(select(KnowledgeChunk.text)
                                 .where(KnowledgeChunk.spawn_id == sid))).scalars().all()
    assert any("OCR EXTRACTED TEXT" in t for t in rows)


async def test_text_layer_pdf_skips_ocr(memdb, monkeypatch):
    sid = await _spawn(memdb)
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: "real text layer content here, plenty of it")
    called = {"ocr": False}
    monkeypatch.setattr(ingest, "_ocr_pdf", lambda data: (called.__setitem__("ocr", True) or "x"))
    await ingest.ingest_file(sid, "doc.pdf", b"%PDF-fake")
    assert called["ocr"] is False


async def test_ocr_error_falls_back_to_text_layer(memdb, monkeypatch):
    sid = await _spawn(memdb)
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: "")
    def boom(data): raise RuntimeError("tesseract missing")
    monkeypatch.setattr(ingest, "_ocr_pdf", boom)
    n = await ingest.ingest_file(sid, "scan.pdf", b"%PDF-fake")
    assert n == 0
