"""Q1b, #486 review G1 (the user, 2026-10-29: "Server fails closed"). A quick question whose store failed could
still run as an ordinary chat with every tool: by a follow-up naming its id, by a new message starting it again
without the kind, or by any message after the Bridge restarted (the Bridge remembered messages, not the
conversation). So the server decides by the conversation:

- a conversation the phone made (`phone-` and a UUID v4) with no kind stored gets only the four quick tools and
  learns nothing;
- the Bridge stores an ordinary new conversation as `chat` before its first message runs, in the one call that
  also checks it is still empty, the way it stores a quick one (POST /phone/conversations/{id}/chat).
"""
import pytest
import sqlalchemy as sa

from server.db.companion_models import ConversationContext
from server.db.models import ArslanMessage
from server.orchestrator import arslan
from server.services import phone_ids, task_context
from tests.server.test_q1a_quick_ask import QUICK, _capture, _row, _say, _store

NEW = "phone-6c7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b"
OTHER = "phone-7c7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b"


# -- the server reads the conversation, never the message -------------------------------------------------------

async def test_a_phone_conversation_with_no_kind_stored_is_read_as_a_quick_question(execution_db, monkeypatch):
    seen = _capture(monkeypatch)
    await arslan._handle_answer(NEW, "and tomorrow?", lambda e: None, source="phone")
    assert seen["shown"] == QUICK and seen["callable"] == QUICK
    assert arslan.QUICK_NOTE in seen["notes"] and arslan.PHONE_NOTE not in seen["notes"]


@pytest.mark.parametrize("cid, kind, learns", [
    (NEW, None, False), (NEW, "chat", True), (NEW, "quick", False), ("c-plain", None, True),
], ids=["phone-made-no-kind", "phone-made-chat", "quick", "made-on-the-mac"])
async def test_only_a_stored_kind_lets_a_phone_conversation_learn(execution_db, cid, kind, learns):
    if kind:
        await _store(execution_db, cid, kind)
    ctx = await task_context.load(cid, user_message="I live in Acme City")
    assert ctx.no_learning is (not learns)


async def test_a_stored_quick_question_never_learns_whatever_its_row_says(execution_db):
    """Its row says no_learning from /quick; one switched on by older code (the window's context PUT before #490)
    still learns nothing while it is a quick question."""
    async with execution_db() as db:
        db.add(ConversationContext(id=NEW, kind="quick", no_learning=False))
        await db.commit()
    assert (await task_context.load(NEW, user_message="I live in Acme City")).no_learning is True


async def test_a_row_with_no_kind_is_read_like_no_row(execution_db):
    """The window's context PUT makes a row without a kind (moving the conversation into a project, say)."""
    async with execution_db() as db:
        db.add(ConversationContext(id=NEW, no_memory=True))
        await db.commit()
    assert (await task_context.load(NEW, user_message="I live in Acme City")).no_learning is True


def test_what_a_conversation_is_comes_from_one_place():
    assert [phone_ids.kind_of(NEW, stored) for stored in (None, "quick", "chat", "sub")] == ["quick", "quick", "chat", "sub"]
    assert [phone_ids.kind_of("c-plain", stored) for stored in (None, "chat")] == [None, "chat"]


def test_a_phone_id_is_exactly_the_shape_the_phone_makes():
    assert phone_ids.made_on_the_phone(NEW)
    for other in ("c-plain", "pocket", "phone-123", NEW.upper(), NEW + "\n", "x" + NEW, None, ""):
        assert not phone_ids.made_on_the_phone(other), other


# -- POST /phone/conversations/{id}/chat ------------------------------------------------------------------------

async def test_a_new_ordinary_conversation_is_stored_as_chat(client):
    async with client.db_maker() as db:
        db.add(ConversationContext(id=NEW, no_memory=True, no_learning=True))    # switches already set stay as they were
        await db.commit()
    got = await client.post(f"/api/v1/phone/conversations/{NEW}/chat")
    assert got.status_code == 200 and got.json() == {"conversation_id": NEW, "kind": "chat"}
    row = await _row(client, NEW)
    assert (row.kind, row.no_learning, row.no_memory) == ("chat", True, True)
    assert (await client.post(f"/api/v1/phone/conversations/{NEW}/chat")).status_code == 200    # a retry
    await client.post(f"/api/v1/phone/conversations/{OTHER}/chat")
    assert (await _row(client, OTHER)).no_learning is False


async def test_one_with_messages_is_never_stored_as_chat(client):
    await _say(client, NEW, "hello", "2026-10-29T08:00:00")
    got = await client.post(f"/api/v1/phone/conversations/{NEW}/chat")
    assert got.status_code == 409 and got.json()["detail"] == "conversation_exists"
    assert await _row(client, NEW) is None


@pytest.mark.parametrize("kind", ["quick", "sub"])
async def test_a_quick_question_or_another_kind_is_never_stored_as_chat(client, kind):
    """Only conversation.update turns a quick question into a chat, the user's own step."""
    async with client.db_maker() as db:
        db.add(ConversationContext(id=OTHER, kind=kind, no_learning=kind == "quick"))
        await db.commit()
    got = await client.post(f"/api/v1/phone/conversations/{OTHER}/chat")
    assert got.status_code == 409 and got.json()["detail"] == "conversation_exists"
    row = await _row(client, OTHER)
    assert (row.kind, row.no_learning) == (kind, kind == "quick")


@pytest.mark.parametrize("conversation_id", ["trip", "phone-not-a-uuid", "phone-6C7C9A2E-1C1D-4F5E-9A8B-3C2D1E0F9A8B",
                                             "pocket"])
async def test_only_a_phone_shaped_new_id_is_stored_as_chat(client, conversation_id):
    got = await client.post(f"/api/v1/phone/conversations/{conversation_id}/chat")
    assert got.status_code == 400 and got.json()["detail"] == "bad_request"
    assert await _row(client, conversation_id) is None


# -- the lists and conversation.update read it the same way ------------------------------------------------------

async def test_a_phone_conversation_with_no_kind_is_listed_with_the_quick_questions(client):
    await _say(client, NEW, "weather?", "2026-10-29T08:00:00")
    await _say(client, "trip", "Plan a trip", "2026-10-29T07:00:00")
    assert [c["conversation_id"] for c in (await client.get("/api/v1/conversations")).json()] == ["trip"]
    quick = (await client.get("/api/v1/phone/conversations?kind=quick")).json()["conversations"]
    assert [(c["id"], c["kind"]) for c in quick] == [(NEW, "quick")]


async def test_a_phone_conversation_with_no_kind_can_be_turned_into_a_chat(client):
    """Read as a quick question, it is turned like one: it learns from after its last message (Q1 #3, #490)."""
    await _say(client, NEW, "weather?", "2026-10-29T08:00:00")
    await _say(client, NEW, "and tomorrow?", "2026-10-29T08:01:00")
    async with client.db_maker() as db:
        last = await db.scalar(sa.select(sa.func.max(ArslanMessage.id)).where(ArslanMessage.conversation_id == NEW))
    got = await client.post(f"/api/v1/phone/conversations/{NEW}/update", json={"kind": "chat"})
    assert got.status_code == 200 and got.json() == {"conversation_id": NEW, "kind": "chat"}
    row = await _row(client, NEW)
    assert (row.kind, row.no_learning, row.learns_after_message_id) == ("chat", False, last)
    never = await client.post(f"/api/v1/phone/conversations/{OTHER}/update", json={"kind": "chat"})
    assert never.status_code == 404 and never.json()["detail"] == "not_found"     # never started: no messages
    assert await _row(client, OTHER) is None
