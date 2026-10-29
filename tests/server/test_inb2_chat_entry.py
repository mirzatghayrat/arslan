"""INB2 through the real chat entry (#475 review, F1): `arslan.handle_user_message` inside
`presence.user_turn()`, as the window's user_message runs it. What the user attached reached the turn as
the user's own words until S64-0b (#443) marked it, so an "about you" entry Arslan wrote from a file or a
picture took effect directly. With anything attached, it waits; with nothing attached, it takes effect.

The harness is S64-0b's: a scripted model, Arslan's tools and the user's yes (offline).

#475 F2 (the user, 2026-10-29): clean is an allowlist. Nothing attached, no project knowledge put into a
turn, and only tools known to be local-only called; anything else keeps it waiting, run_command reading a
file included, and the run's record (`runs.read_outside`) says the same for later turns.
"""
import pytest
from sqlalchemy import select

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.db.companion_models import MemoryEntry, MemoryRevision
from server.services import knowledge, ocr_fallback, presence
from server.services.memory_repository import repository
from server.orchestrator import arslan, tool_loop, untrusted
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


# -- #475 F2 (the user, 2026-10-29): clean is an allowlist ------------------------------------------------

CAT = ("run_command", {"command": "cat notes.txt"})        # reads a file and reaches no network


async def _status_of(entry, text) -> str:
    async with entry.db() as db:
        return (await db.scalars(select(MemoryEntry.status).join(
            MemoryRevision, MemoryRevision.id == MemoryEntry.current_revision_id).where(
            MemoryRevision.content == text))).one()


async def test_a_command_reading_a_file_keeps_about_you_waiting(entry):
    """run_command can read a file, so it counts even when the command reaches no network (the
    outside-content mark counts only those, and still does for lessons and Arslan's own notes)."""
    assert await _about_you(entry, _Model(chat=_turn(CAT, ABOUT_YOU))) == ["proposed"]


async def test_project_knowledge_put_into_the_turn_keeps_about_you_waiting(entry, monkeypatch):
    async def found(*args, **kwargs):
        return [("setup.md", POISON)]
    monkeypatch.setattr(knowledge, "retrieve_scoped", found)
    assert await _about_you(entry, _Model(chat=_turn(ABOUT_YOU))) == ["proposed"]


async def test_a_call_off_the_allowlist_counts_even_when_it_never_ran(entry):
    """Called is enough: this turn cannot run desktop_look at all (K7 answers "not available")."""
    assert await _about_you(entry, _Model(chat=_turn(("desktop_look", {}), ABOUT_YOU))) == ["proposed"]


async def test_a_command_in_an_earlier_turn_keeps_about_you_waiting_later(entry):
    """The run's record is the allowlist too, so the next turn of the conversation waits."""
    model = _Model(chat=_turn(CAT) + _turn(ABOUT_YOU))
    await entry(model)
    assert await _about_you(entry, model) == ["proposed"]


async def test_a_clean_earlier_turn_leaves_the_next_one_clean(entry):
    model = _Model(chat=_turn() + _turn(ABOUT_YOU))           # the first turn only answers
    await entry(model)
    assert await _about_you(entry, model) == ["active"]


async def test_memory_note_answering_with_the_sets_entries_counts(entry):
    """A full set, or an id not in it, comes back with the set's entries, waiting ones too: stored text,
    like recall. Here a waiting entry from an earlier, unclean conversation."""
    async with repository() as repo:
        await repo.create(MemoryWrite(content=POISON, kind="preference", scope=MemoryScope(kind="global"),
                                      core="about_you"), MemoryActor(origin="host"))
    listing = ("memory_note", {"action": "remove", "set": "about_you", "id": "not-in-the-set"})
    with presence.user_turn():
        await entry(_Model(chat=_turn(listing, ABOUT_YOU)))
    assert await _status_of(entry, ABOUT_YOU[1]["text"]) == "proposed"


@pytest.mark.parametrize("first", [
    ("update_plan", {"items": [{"text": "Note what the user said", "status": "in_progress"}]}),
    ("remember", {"action": "append", "kind": "preference", "content": "The user writes in British English"}),
    ("memory_note", {"action": "remove", "set": "about_you", "id": "not-in-the-set"}),
], ids=["checklist", "remember", "memory_note-with-an-empty-set"])
async def test_known_local_calls_keep_the_turn_clean(entry, monkeypatch, first):
    async def tools():
        return [{"key": key, "description": "fixture"}
                for key in ("memory_note", "remember", "update_plan", "run_command", "web_extract")]
    monkeypatch.setattr(arslan, "_arslan_tools", tools)
    assert set(await _about_you(entry, _Model(chat=_turn(first, ABOUT_YOU)))) == {"active"}


@pytest.mark.parametrize("found", [[], [("setup.md", POISON)]], ids=["no-knowledge", "knowledge"])
async def test_project_knowledge_in_a_background_job_counts_too(execution_db, monkeypatch, found):
    """A job never runs with the user present, but its run's record is what later turns check."""
    seen = {}

    async def run_native(**kwargs):
        token = untrusted.track_turn()
        seen["known_local"] = untrusted.known_local()
        untrusted.end_turn(token)
        return {"final": "ok", "tool_trace": []}

    async def context(conversation_id, **kwargs):
        return {"summary": "", "history": [{"role": "user", "content": "copy the invoices"}]}

    async def facts_text(include_sensitive=False):
        return ""

    async def retrieve(*args, **kwargs):
        return found
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    monkeypatch.setattr(arslan.memory, "assemble_working_context", context)
    monkeypatch.setattr(arslan.memory, "facts_text", facts_text)
    monkeypatch.setattr(knowledge, "retrieve_scoped", retrieve)

    class Confirm:
        command = workspace_write = schedule = None
    await arslan.background_body("c-bg", "copy the invoices", lambda e: None, Confirm())
    assert seen["known_local"] is (not found)
