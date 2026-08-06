"""The tier-1 -> tier-2 handover, asserted on the REAL ingest path.

A helper that works perfectly and is never called passes its own unit tests.
That has caught me three times in this codebase, so the assertions here run
ingest_file end to end against a real database and read back what was stored.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.migrations.versions._0009_knowledge import upgrade_sync
from server.db.models import Base, KnowledgeChunk, Spawn
from server.services import ingest, ocr_fallback, ocr_vision

# The exact wording a provider uses when it will not take an image. Not invented
# for this test: it is the phrasing vision_errors matches on, and the reason the
# matcher is shared rather than duplicated.
REFUSAL = "Error code: 400 - this model does not support image input"
UNRELATED = "Error code: 429 - rate limit exceeded, please retry"


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


def _png_with(text: str) -> bytes:
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 44)
    except OSError:  # pragma: no cover - host font layout
        font = ImageFont.load_default()
    img = Image.new("RGB", (760, 120), "white")
    ImageDraw.Draw(img).text((20, 30), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


async def _sources(Session, sid) -> list[str]:
    async with Session() as db:
        return list((await db.execute(
            select(KnowledgeChunk.source).where(KnowledgeChunk.spawn_id == sid)
        )).scalars().all())


async def _texts(Session, sid) -> list[str]:
    async with Session() as db:
        return list((await db.execute(
            select(KnowledgeChunk.text).where(KnowledgeChunk.spawn_id == sid)
        )).scalars().all())


needs_vision = pytest.mark.skipif(
    not ocr_vision.is_available(), reason="no system recogniser on this host"
)


# @pytest.mark.macos is a SELECTION marker added alongside the `needs_vision`
# skipif above — never instead of it. That skipif gates on
# ocr_vision.is_available() rather than on sys.platform, so it reads as a
# capability check; on Linux there is no system recogniser and these skip.
# Measured 2026-08-06: part of a 25-test set that skips on Linux and had never
# executed on any CI runner.
@pytest.mark.macos
@needs_vision
async def test_a_model_that_cannot_see_hands_off_to_the_system_recogniser(
        memdb, monkeypatch):
    """The whole point of the round, asserted from the outside."""
    sid = await _spawn(memdb)

    async def refuses(data, mime):
        raise RuntimeError(REFUSAL)

    monkeypatch.setattr(ingest, "describe_image", refuses)
    monkeypatch.setattr(ocr_fallback, "current_ui_language", _en)

    stored = await ingest.ingest_file(sid, "note.png", _png_with("tier two read this"))

    assert stored >= 1, "the handover produced no chunks"
    assert "tier two read this" in " ".join(await _texts(memdb, sid))


@pytest.mark.macos
@needs_vision
async def test_an_unrelated_failure_does_not_start_an_ocr_pass(memdb, monkeypatch):
    """Discriminating twin of the test above.

    Without this, a fallback wired to `except Exception` would pass the happy
    case and quietly relabel every rate limit as a vision problem — which is the
    failure vision_errors was written to prevent in the first place."""
    sid = await _spawn(memdb)
    ran = []

    async def refuses(data, mime):
        raise RuntimeError(UNRELATED)

    monkeypatch.setattr(ingest, "describe_image", refuses)
    monkeypatch.setattr(ocr_fallback, "read_locally",
                        lambda *a, **k: ran.append(1) or ("x", ocr_vision.OK))

    stored = await ingest.ingest_file(sid, "note.png", _png_with("do not read me"))

    assert stored == 0
    assert ran == [], "a rate limit started an OCR pass"


@pytest.mark.macos
@needs_vision
async def test_transcription_and_description_are_labelled_differently(
        memdb, monkeypatch):
    """Decision ②A, checked where it actually matters: the stored provenance.

    A retrieval hit renders as "[source] text", so these two strings are what
    the model is told about the trustworthiness of the words that follow. One is
    characters lifted off the picture; the other is a model's account of it."""
    sid = await _spawn(memdb)

    async def describes(data, mime):
        return "a photograph of a whiteboard"

    monkeypatch.setattr(ingest, "describe_image", describes)
    await ingest.ingest_file(sid, "described.png", _png_with("ignored"))

    async def refuses(data, mime):
        raise RuntimeError(REFUSAL)

    monkeypatch.setattr(ingest, "describe_image", refuses)
    monkeypatch.setattr(ocr_fallback, "current_ui_language", _en)
    await ingest.ingest_file(sid, "transcribed.png", _png_with("exact words here"))

    sources = await _sources(memdb, sid)
    transcribed = ocr_fallback.ocr_source("transcribed.png")
    described = ingest.described_source("described.png")

    assert transcribed in sources, sources
    assert described in sources, sources
    # The load-bearing assertion: the two markers must be DISTINGUISHABLE.
    # Comparing against the real functions rather than literals means this
    # keeps its meaning if either wording is translated later — what must not
    # change is that a transcription cannot be mistaken for a description.
    assert transcribed != described
    assert "OCR" in transcribed and "OCR" not in described


async def test_both_routes_go_through_the_one_degradation_helper(
        memdb, monkeypatch):
    """There must be a single fallback rule, not one per entry point.

    The brain-feed route and the /extract route are asserted to funnel into the
    same function; before this round they had DIFFERENT behaviour for the same
    file, which is what a second copy of the rule buys you."""
    sid = await _spawn(memdb)
    seen = []

    def spy(data, *, ui_language=None, chosen_languages=None):
        # The double must track the real signature: when read_locally grew the
        # explicit-language argument, a stale spy raised TypeError inside the
        # except block and the test failed as if the wiring had broken.
        seen.append(ui_language)
        return "spied", ocr_vision.OK

    monkeypatch.setattr(ocr_fallback, "read_locally", spy)
    monkeypatch.setattr(ocr_vision, "is_available", lambda: True)

    async def refuses(data, mime):
        raise RuntimeError(REFUSAL)

    monkeypatch.setattr(ingest, "describe_image", refuses)
    monkeypatch.setattr(ocr_fallback, "current_ui_language", _en)

    await ingest.ingest_file(sid, "brain.png", _png_with("x"))          # route 1
    ingest._extract_file("chat.png", _png_with("x"), ui_language="en")              # route 2

    assert len(seen) == 2, "one of the two routes bypasses the shared helper"


async def _en():
    return "en"


def test_the_ui_locale_decides_which_languages_are_asked_for():
    assert ocr_vision.vision_tags_for("zh") == ("zh-Hans", "en-US")
    assert ocr_vision.vision_tags_for("en") == ("en-US",)
    # An unknown locale must not invent a tag — it falls back to English rather
    # than handing Vision something it will treat as a wrong-script guess.
    assert ocr_vision.vision_tags_for("ug") == ("en-US",)
    assert ocr_vision.vision_tags_for(None) == ("en-US",)


def test_no_text_says_which_language_it_looked_for():
    """"Nothing was found" is misleading when the reason is "we looked in the
    wrong language" — and that is the case that actually happens, because a
    fresh install asks for English only. Measured: widening the request does
    not fix it (all thirty languages loses Chinese), so the user needs the
    reason, not a broader search."""
    msg = ocr_fallback.explain_status(ocr_vision.NO_TEXT, ("zh-Hans", "en-US"))
    assert "zh-Hans" in msg and "en-US" in msg
    # Discriminating: a message that merely said "no writing was found" would
    # satisfy any assertion about non-emptiness, so pin the actionable half too.
    assert "interface language" in msg

    # The genuinely blank case still reads sensibly.
    assert "No writing was found" in ocr_fallback.explain_status(ocr_vision.NO_TEXT)


def test_an_unsupported_language_lists_what_the_host_can_do(monkeypatch):
    monkeypatch.setattr(ocr_vision, "supported_languages", lambda: ("en-US", "fr-FR"))
    msg = ocr_fallback.explain_status(ocr_vision.UNSUPPORTED_LANGUAGE)
    assert "en-US, fr-FR" in msg
