"""Stage 4: an image fed to the second brain is DESCRIBED by the model, and the
stored description can never be mistaken for text taken from the picture.

Decision ④A plus the user's addition: the description carries a provenance
marker so a retrieval hit is not quoted as if it were verbatim source.

The marker lives on `source`, not as a text prefix, for a specific reason: a
description long enough to be chunked would carry a text prefix on the FIRST
chunk only, while `source` is stored on EVERY chunk and is rendered into the
model's view by knowledge_block ("[source] text") and by the recall executor.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.services import ingest, knowledge


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'vi.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def test_described_source_is_marked():
    assert ingest.described_source("shot.png") == "shot.png (image description)"


def test_marker_is_stable_not_localised():
    """Stored data, like FACT_CATEGORIES: the marker is a stable machine-readable
    string. A translated marker would mean the same picture reads differently
    depending on which language the app happened to be in when it was fed."""
    src = ingest.described_source("图.png")
    assert "image description" in src
    assert src == ingest.described_source("图.png")


def test_marker_reaches_the_model_through_the_knowledge_block():
    """The point of the whole exercise: whatever the model sees must say this is
    a description. knowledge_block renders '[source] text'."""
    block = knowledge.knowledge_block([(ingest.described_source("shot.png"), "a red login screen")])
    assert "image description" in block
    assert "a red login screen" in block


@pytest.mark.asyncio
async def test_every_chunk_carries_the_marker(maker, monkeypatch):
    """A long description splits into several chunks. A text PREFIX would mark
    only the first — this is the case that chose the design."""
    long_description = ("The screenshot shows a settings page. " * 200).strip()

    async def _fake_describe(data: bytes, mime: str) -> str:
        return long_description

    monkeypatch.setattr(ingest, "describe_image", _fake_describe)
    n = await ingest.ingest_file(None, "shot.png", b"\x89PNG\r\n\x1a\nX", collection_id=1)
    assert n > 1, "fixture must produce MULTIPLE chunks or it proves nothing"
    async with maker() as s:
        sources = [r[0] for r in (await s.execute(sa_text(
            "SELECT source FROM knowledge_chunks"))).all()]
    assert sources and all("image description" in x for x in sources)


@pytest.mark.asyncio
async def test_a_failed_description_stores_nothing(maker, monkeypatch):
    """Same honesty contract as the hotfix: no description ⇒ 0 chunks, so the UI
    says it could not read the image instead of claiming success."""
    async def _boom(data: bytes, mime: str) -> str:
        raise RuntimeError("no vision model configured")

    monkeypatch.setattr(ingest, "describe_image", _boom)
    assert await ingest.ingest_file(None, "shot.png", b"\x89PNG\r\n\x1a\nX", collection_id=1) == 0


@pytest.mark.asyncio
async def test_documents_are_untouched_by_any_of_this(maker):
    """Discrimination: a .md must still be stored under its plain filename —
    marking everything would make the marker meaningless."""
    n = await ingest.ingest_file(
        None, "notes.md", b"# Title\n\nplenty of words here to chunk", collection_id=1)
    assert n > 0
    async with maker() as s:
        src = (await s.execute(sa_text(
            "SELECT source FROM knowledge_chunks LIMIT 1"))).scalar_one()
    assert src == "notes.md"
