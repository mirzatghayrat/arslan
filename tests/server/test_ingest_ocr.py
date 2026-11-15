"""Ingest-side OCR routing.

PLATFORM PREMISE, written down because this file had none and that was a latent
trap. These tests are CROSS-PLATFORM: they need `pypdfium2` (a declared runtime
dependency, pyproject.toml) and nothing macOS-specific, so they run and pass on
Linux CI today. They carry no skip marker deliberately.

DO NOT "fix" a missing pypdfium2 by adding a skip. A declared dependency that is
absent is an environment bug and should fail loudly — measured 2026-08-06, a
stale local venv made these six error with ModuleNotFoundError while CI was
green, and the first instinct was to read that as a platform difference. Turning
it into a skip would have converted a loud, fixable environment fault into a
silent pass, which is the exact failure this project spent a round removing from
its CI report.

If a test HERE ever grows a real macOS dependency, mark it @pytest.mark.macos
alongside its own skipif — see test_ocr_vision.py for the composing form.
"""
import pytest
from sqlalchemy import select
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


async def test_no_text_layer_goes_to_the_vision_path_not_ocr(memdb, monkeypatch):
    """CONTRACT CHANGE (vision round): a scan without a text layer is now READ BY
    THE MODEL, not handed to tesseract. The old assertion described the
    behaviour this round deliberately replaced — tesseract is not in the
    packaged app at all, which is why scanned PDFs were unreadable in every
    shipped build."""
    import io

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    pdf.new_page(200, 300)
    buf = io.BytesIO()
    pdf.save(buf)

    cid = await _collection(memdb)

    async def _describe(data: bytes, mime: str) -> str:
        return "MODEL READ THIS SCAN"

    monkeypatch.setattr(ingest, "describe_image", _describe)
    # Deliberately NOT stubbing _ocr_pdf: if the implementation still reached
    # for it, this test would fail rather than quietly exercise a stub.
    n = await ingest.ingest_file(None, "scan.pdf", buf.getvalue(), collection_id=cid)
    assert n >= 1
    async with memdb() as db:
        rows = (await db.execute(select(KnowledgeChunk.text)
                                 .where(KnowledgeChunk.collection_id == cid))).scalars().all()
    assert any("MODEL READ THIS SCAN" in t for t in rows)


async def test_text_layer_pdf_skips_ocr(memdb, monkeypatch):
    cid = await _collection(memdb)
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: ingest.PDFTextLayer(("real text layer content here, plenty of it",)))
    called = {"ocr": False}
    monkeypatch.setattr(ingest, "_ocr_pdf", lambda data: (called.__setitem__("ocr", True) or "x"))
    await ingest.ingest_file(None, "doc.pdf", b"%PDF-fake", collection_id=cid)
    assert called["ocr"] is False


async def test_ocr_error_falls_back_to_text_layer(memdb, monkeypatch):
    cid = await _collection(memdb)
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: ingest.PDFTextLayer(("",)))
    def boom(data): raise RuntimeError("tesseract missing")
    monkeypatch.setattr(ingest, "_ocr_pdf", boom)
    n = await ingest.ingest_file(None, "scan.pdf", b"%PDF-fake", collection_id=cid)
    assert n == 0
