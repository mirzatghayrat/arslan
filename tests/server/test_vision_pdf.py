"""Stage 5: a scanned PDF is rasterised and read by the model, under a cap.

The cap exists because every page is a separately billed image. The number is
NOT arbitrary and NOT about money — see VISION_PDF_MAX_PAGES for the arithmetic
that chose it. Over the cap the result SAYS what was skipped: silent truncation
would let a user act on 36 pages of a 137-page contract believing they had all
of it.

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
from __future__ import annotations

import pytest

from server.services import ingest


def test_the_cap_has_the_agreed_default():
    assert ingest.VISION_PDF_MAX_PAGES == 36


def test_pages_under_the_cap_are_all_taken():
    assert ingest.pdf_page_plan(12) == (12, "")


def test_over_the_cap_reports_what_it_skipped():
    taken, note = ingest.pdf_page_plan(137)
    assert taken == 36
    # The exact numbers must be in the note — "some pages were skipped" is the
    # kind of message that lets someone quote a contract they never read.
    assert "137" in note and "36" in note


def test_the_note_is_empty_exactly_when_nothing_was_skipped():
    """Discrimination: always emitting a note would make it noise, and never
    emitting one is the silent truncation this test exists to prevent."""
    assert ingest.pdf_page_plan(36)[1] == ""
    assert ingest.pdf_page_plan(37)[1] != ""


def test_a_zero_page_document_is_not_a_crash():
    assert ingest.pdf_page_plan(0) == (0, "")


@pytest.mark.parametrize("pages", [1, 35, 36, 37, 500])
def test_never_returns_more_than_the_cap(pages):
    taken, _ = ingest.pdf_page_plan(pages)
    assert taken <= ingest.VISION_PDF_MAX_PAGES
    assert taken <= pages


# ── rasterisation: the real library, no stubs on the thing under test ────────

def _one_page_pdf(pages: int = 1) -> bytes:
    """A real PDF with NO text layer, built with the same library that will read
    it back. Stubbing the rasteriser would leave the actual integration —
    the part that broke before — untested."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(200, 300)
    import io

    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def test_a_scanned_page_rasterises_to_png_bytes():
    from server.services import ingest

    pages = ingest.rasterize_pdf(_one_page_pdf(2), max_pages=5)
    assert len(pages) == 2
    # PNG magic — proves we produced an actual image, not an empty buffer.
    assert all(p.startswith(b"\x89PNG\r\n\x1a\n") for p in pages)


def test_rasterising_obeys_the_cap():
    from server.services import ingest

    assert len(ingest.rasterize_pdf(_one_page_pdf(5), max_pages=3)) == 3


import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

import server.db.session as db_session  # noqa: E402
from server.db.models import Base  # noqa: E402


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'p.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_a_scanned_pdf_is_described_page_by_page(maker, monkeypatch):
    from sqlalchemy import text as sa_text

    from server.services import ingest

    seen = []

    async def _describe(data: bytes, mime: str) -> str:
        seen.append(data)
        return f"page {len(seen)} shows a form"

    monkeypatch.setattr(ingest, "describe_image", _describe)
    n = await ingest.ingest_file(None, "scan.pdf", _one_page_pdf(3), collection_id=1)
    assert n > 0
    assert len(seen) == 3, "every page within the cap must be read"
    async with maker() as s:
        src = (await s.execute(sa_text(
            "SELECT source FROM knowledge_chunks LIMIT 1"))).scalar_one()
    # A described scan is a description, exactly like a described image.
    assert "image description" in src


@pytest.mark.asyncio
async def test_over_the_cap_the_stored_text_says_so(maker, monkeypatch):
    from sqlalchemy import text as sa_text

    from server.services import ingest

    monkeypatch.setattr(ingest, "VISION_PDF_MAX_PAGES", 2)

    calls: list[int] = []

    async def _describe(data: bytes, mime: str) -> str:
        calls.append(1)
        return "a page"

    monkeypatch.setattr(ingest, "describe_image", _describe)
    await ingest.ingest_file(None, "big.pdf", _one_page_pdf(5), collection_id=1)
    async with maker() as s:
        texts = " ".join(r[0] for r in (await s.execute(sa_text(
            "SELECT text FROM knowledge_chunks"))).all())
    # Assert the NOTE, not bare digits: "5" and "2" also appear as page numbers,
    # so a digit check passes even when the cap is ignored entirely — which a
    # mutation proved before this assertion was tightened.
    assert "were read" in texts and "The rest were not" in texts
    # And prove the cap actually bit: exactly 2 of the 5 pages were read.
    assert len(calls) == 2, f"cap ignored — {len(calls)} pages went to the model"


@pytest.mark.asyncio
async def test_a_pdf_with_a_text_layer_never_reaches_the_model(maker, monkeypatch):
    """Discrimination: rasterising a normal PDF would burn tokens on something
    pypdf already reads for free."""
    from server.services import ingest

    called = []

    async def _describe(data: bytes, mime: str) -> str:
        called.append(1)
        return "should not happen"

    monkeypatch.setattr(ingest, "describe_image", _describe)
    monkeypatch.setattr(ingest, "_pdf_text_layer",
                        lambda data: "A real text layer with plenty of words in it.")
    # A REAL pdf, not a stub blob: with a fake one, removing the text-layer
    # shortcut makes rasterisation RAISE, describe_image is never reached, and
    # the assertion passes for entirely the wrong reason. A mutation caught
    # exactly that before this line was fixed.
    await ingest.ingest_file(None, "doc.pdf", _one_page_pdf(2), collection_id=1)
    assert called == [], "a text-layer PDF must not be sent to the vision model"
