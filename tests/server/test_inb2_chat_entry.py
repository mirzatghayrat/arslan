"""INB2 through the real chat entry (#475 review, F1): `arslan.handle_user_message` inside
`presence.user_turn()`, as the window's user_message runs it. What the user attached reached the turn as
the user's own words until S64-0b (#443) marked it, so an "about you" entry Arslan wrote from a file or a
picture took effect directly. With anything attached, it waits; with nothing attached, it takes effect.

The harness is S64-0b's: a scripted model, Arslan's tools and the user's yes (offline).
"""
import pytest
from sqlalchemy import select

from server.db.companion_models import MemoryEntry
from server.services import ocr_fallback, presence
from server.orchestrator import arslan
from tests.server.test_s64_0b_attachments_and_job_results import (  # noqa: F401  (the fixture)
    PICTURE, POISON, _Model, _turn, chat)

ABOUT_YOU = ("memory_note", {"action": "add", "set": "about_you", "text": "The user prefers short answers"})


@pytest.fixture
async def entry(chat):  # noqa: F811 — S64-0b's fixture, requested by its name
    """S64-0b's chat entry (the real handle_user_message, offline), under this module's own name."""
    yield chat


async def _about_you(entry, model, **kw) -> list[str]:
    with presence.user_turn():
        await entry(model, **kw)
    async with entry.db() as db:
        return list((await db.scalars(select(MemoryEntry.status).where(MemoryEntry.kind == "preference"))).all())


async def test_present_with_nothing_attached_about_you_takes_effect(entry):
    assert await _about_you(entry, _Model(chat=_turn(ABOUT_YOU))) == ["active"]


async def test_an_attached_file_keeps_about_you_waiting(entry):
    assert await _about_you(entry, _Model(chat=_turn(ABOUT_YOU)), attached=POISON) == ["proposed"]


async def test_an_attached_picture_keeps_about_you_waiting(entry):
    assert await _about_you(entry, _Model(chat=_turn(ABOUT_YOU)), images=[PICTURE]) == ["proposed"]


async def test_text_read_off_a_picture_the_model_refused_keeps_about_you_waiting(entry, monkeypatch):
    async def read(images):
        return POISON
    monkeypatch.setattr(ocr_fallback, "model_refused_the_image", lambda error: True)
    monkeypatch.setattr(arslan, "_read_images_locally", read)
    model = _Model(chat=_turn(ABOUT_YOU), refuse_pictures=True)
    assert await _about_you(entry, model, images=[PICTURE]) == ["proposed"]
    assert model.chat_turn == []                                   # the retry without the picture ran


@pytest.mark.parametrize("attached", [None, POISON], ids=["nothing", "file"])
async def test_not_present_it_waits_either_way(entry, attached):
    await entry(_Model(chat=_turn(ABOUT_YOU)), attached=attached)
    async with entry.db() as db:
        assert (await db.scalars(select(MemoryEntry.status).where(MemoryEntry.kind == "preference"))).all() == [
            "proposed"]
