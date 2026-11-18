"""v0.1.64 fix: attach_file is resident in a chat turn, and a quick ask says how to get what it can't do.

On demand, sending a file took find_tools and then use_tool, and a model stopped after the first hop with a
screenshot it had taken never sent. A quick ask from the phone keeps exactly its four read-only tools; when it is
asked for something on the Mac, its note tells the model to say so and to point at the phone's 「新对话」 or the Mac.
"""
from server.db.companion_models import ConversationContext
from server.orchestrator import arslan, tool_loop

QUICK_ID = "phone-5d1e2f3a-4b5c-4d6e-8f70-81a2b3c4d5e6"
HANDOFF = "say plainly that a quick ask can't do that"


async def _store(db, conversation_id, kind):
    async with db() as session:
        session.add(ConversationContext(id=conversation_id, kind=kind, no_learning=kind == "quick"))
        await session.commit()


def _capture(monkeypatch) -> dict:
    seen = {}

    async def run_native(*, system, user_content, on_chunk, resolve_tools, resolve_callable, turn_notes=None, **kw):
        seen["system"] = system
        seen["shown"] = [tool["key"] for tool in await resolve_tools()]
        seen["callable"] = {tool["key"] for tool in await resolve_callable()}
        seen["notes"] = "\n".join(turn_notes or [])
        on_chunk("ok")
        return {"final": "ok", "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    return seen


async def test_a_chat_turn_is_shown_attach_file_by_name(execution_db, monkeypatch):
    seen = _capture(monkeypatch)
    await arslan._handle_answer("c-plain", "send me a screenshot", lambda e: None, source="phone")
    # Shown in the resident table itself, not appended after an on-demand use.
    assert "attach_file" in seen["shown"][:seen["shown"].index("find_tools")]
    assert "find_tools" not in arslan.PHONE_NOTE and "attach_file" in seen["notes"]


async def test_a_quick_ask_is_shown_exactly_the_quick_tools(execution_db, monkeypatch):
    await _store(execution_db, QUICK_ID, "quick")
    seen = _capture(monkeypatch)
    await arslan._handle_answer(QUICK_ID, "send me a screenshot", lambda e: None, source="phone")
    assert set(seen["shown"]) == set(arslan.QUICK_TOOLS) == seen["callable"]
    assert len(seen["shown"]) == len(arslan.QUICK_TOOLS) == 4
    assert arslan.QUICK_TOOLS == {"web_search", "web_extract", "recall", "conversation_search"}


async def test_a_quick_ask_is_told_to_hand_off_with_the_phones_label(execution_db, monkeypatch):
    await _store(execution_db, QUICK_ID, "quick")
    seen = _capture(monkeypatch)
    await arslan._handle_answer(QUICK_ID, "send me a screenshot", lambda e: None, source="phone")
    assert HANDOFF in seen["notes"] and "「新对话」" in seen["notes"] and "ask on the Mac" in seen["notes"]
    assert "a screenshot, a file, running something, acting on the Mac" in arslan.QUICK_NOTE


async def test_a_chat_turn_is_not_told_to_hand_off(execution_db, monkeypatch):
    seen = _capture(monkeypatch)
    await arslan._handle_answer("c-plain", "send me a screenshot", lambda e: None, source="phone")
    for text in (seen["notes"], seen["system"]):
        assert HANDOFF not in text and "新对话" not in text
