"""The shipped-0.1.6 silent lie: an image fed to the second brain stored zero
chunks while the UI reported success.

Test-bed note (this is the point of the file): the pre-existing
tests/server/test_ingest_ocr.py stubs `_ocr_pdf` — the function under test —
at every call site, which is exactly why swapping the OCR implementation could
never turn any test red. Nothing here stubs an extractor.

Two techniques, deliberately kept apart:

* The CONTRACT ("nothing extracted ⇒ nothing stored ⇒ 0, not an exception") is
  driven with input that genuinely extracts to empty. No simulation at all, so
  it holds in every environment.
* The IMAGE case additionally needs the packaged app's condition — no OCR stack
  — which differs per environment (dev: absent; CI installs `--extra ocr`;
  packaged: absent). So the test IMPOSES that condition by blocking the import,
  and asserts the block took effect first. `_ocr_image`'s real body, including
  its except branch, still runs.
"""
from __future__ import annotations

import io
import sys

import pytest
import pytest_asyncio
from sqlalchemy import text as sa_text
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


@pytest.fixture
def no_ocr_stack(monkeypatch):
    """Impose the packaged app's condition: `import pytesseract` fails.
    A None entry in sys.modules makes the import statement raise ImportError —
    the same thing that happens in the .dmg, at the same line."""
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    return None


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


def test_the_no_ocr_condition_is_really_imposed(no_ocr_stack):
    """⓪ pre-assertion: if the block does not take, the image assertion below
    would pass or fail for reasons unrelated to what it claims to test.
    (This failed once in CI for real — CI installs `--extra ocr`, so the earlier
    version of this file, which assumed the ambient env, was testing nothing
    there.)"""
    with pytest.raises(ImportError):
        import pytesseract  # noqa: F401


def test_image_extracts_to_nothing_without_the_ocr_stack(no_ocr_stack):
    # Real _extract_file, real _ocr_image body, real except branch.
    assert ingest._extract_file("shot.png", _png_bytes()) == ""


def test_a_readable_file_still_extracts(no_ocr_stack):
    """Discrimination: the empty above is caused by the unreadable IMAGE, not by
    extraction being broken for everything while the OCR block is in place."""
    assert "Heading" in ingest._extract_file("notes.md", b"# Heading\n\nSome prose.")


@pytest.mark.asyncio
async def test_empty_extraction_stores_nothing_and_returns_zero(maker):
    """The honest contract the UI must respect: a file that yields no text is a
    200 with a HARD ZERO, not an exception. A caller that only watches for
    exceptions calls it a success — which is precisely the shipped bug.
    Whitespace-only input reaches this outcome with zero simulation."""
    n = await ingest.ingest_file(None, "blank.md", b"   \n\n  \t ", collection_id=1)
    assert n == 0
    async with maker() as s:
        rows = (await s.execute(sa_text("SELECT COUNT(*) FROM knowledge_chunks"))).scalar_one()
    assert rows == 0, "nothing may be persisted when extraction produced nothing"


@pytest.mark.asyncio
async def test_readable_file_still_ingests(maker):
    """Discrimination for the async path: the zero above is about empty content,
    not a broken fixture."""
    n = await ingest.ingest_file(
        None, "notes.md", b"# Heading\n\nA paragraph with enough words to chunk.",
        collection_id=1)
    assert n > 0


@pytest.mark.asyncio
async def test_unreadable_image_ingests_to_zero(maker, no_ocr_stack):
    """The shipped bug's exact input: a real image, no OCR stack, 0 chunks."""
    assert await ingest.ingest_file(None, "shot.png", _png_bytes(), collection_id=1) == 0
