"""The shipped-0.1.6 silent lie: an image fed to the second brain stored zero
chunks while the UI reported success.

These tests deliberately use NO monkeypatch on the extraction stack. The dev
environment has no pytesseract and no pypdfium2 — the same shape as the packaged
app — so `_ocr_image` genuinely fails here and we exercise the REAL production
path. The pre-existing tests/server/test_ingest_ocr.py stubs `_ocr_pdf` at every
call site, which is exactly why swapping the OCR implementation could never turn
any test red.
"""
from __future__ import annotations

import io

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import ingest


def _png_bytes() -> bytes:
    """A real 8x8 PNG — decodable by PIL, so the failure under test is the
    MISSING OCR STACK, not corrupt input."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'feed.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FTS5 mirror is a virtual table, invisible to metadata.create_all.
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)  # DB only — never the extractor
    return m


def test_ocr_stack_is_absent_here_like_in_the_packaged_app():
    """⓪ pre-assertion: if this fails, every assertion below is meaningless
    because OCR would actually succeed."""
    with pytest.raises(ImportError):
        import pytesseract  # noqa: F401


def test_image_extraction_yields_nothing_without_the_ocr_stack():
    # Real _extract_file, real _ocr_image, real absent pytesseract.
    assert ingest._extract_file("shot.png", _png_bytes()) == ""


@pytest.mark.asyncio
async def test_image_ingest_reports_zero_chunks_rather_than_raising(maker):
    """The honest contract the UI must respect: this is a 200 with a HARD ZERO,
    not an exception. A caller that only watches for exceptions will call it a
    success — which is precisely the shipped bug."""
    n = await ingest.ingest_file(None, "shot.png", _png_bytes(), collection_id=1)
    assert n == 0
    async with maker() as s:
        from sqlalchemy import text as sa_text

        rows = (await s.execute(sa_text("SELECT COUNT(*) FROM knowledge_chunks"))).scalar_one()
    assert rows == 0, "nothing may be persisted when extraction produced nothing"


@pytest.mark.asyncio
async def test_readable_file_still_ingests(maker):
    """Discrimination: the zero above must be caused by the unreadable IMAGE,
    not by the fixture/ingest path being broken for everything."""
    n = await ingest.ingest_file(
        None, "notes.md", b"# Heading\n\nA paragraph with enough words to chunk.",
        collection_id=1)
    assert n > 0
