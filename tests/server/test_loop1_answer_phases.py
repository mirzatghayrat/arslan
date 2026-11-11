"""What `_handle_answer_body` does around the tool loop that no other test pinned (LOOP1 c3c split it into phases):
a resumed task's notes reach the request, and a choice card with no text before it closes the stream without a
bubble."""
from sqlalchemy import select

import server.db.session as db_session
from server.db.models import ArslanMessage
from server.orchestrator import arslan, tool_loop
from tests.server.test_promise_guard import maker  # noqa: F401 — a chat database for arslan.handle_user_message


async def test_a_resumed_tasks_notes_reach_the_request(maker, monkeypatch):  # noqa: F811
    seen = []

    async def run_native(**kwargs):
        seen.append(kwargs["user_content"])
        return {"final": "Done.", "escalation": None, "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    await arslan._handle_answer("main", "go on", lambda _frame: None, extra_system="Resume from step three.")
    assert len(seen) == 1 and "Resume from step three." in str(seen[0])


async def test_a_picture_reaches_the_request(maker, monkeypatch):  # noqa: F811
    seen = []

    async def run_native(**kwargs):
        seen.append(kwargs["user_content"])
        return {"final": "Done.", "escalation": None, "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    picture = {"name": "shot.png", "mime_type": "image/png", "data": "QUJDRA=="}
    await arslan._handle_answer("main", "what is on it", lambda _frame: None, images=[picture])
    assert len(seen) == 1
    assert [b for b in seen[0] if isinstance(b, dict) and b.get("type") == "image"] == [
        {"type": "image", "mime_type": "image/png", "data": "QUJDRA=="}]


async def test_an_attachments_links_reach_the_sources_footer(maker, monkeypatch):  # noqa: F811
    async def run_native(**_kwargs):
        return {"final": "Done.", "escalation": None, "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    reply = await arslan._handle_answer("main", "sum it up", lambda _frame: None,
                                        attached_context="From https://example.com/attached-source")
    assert reply.startswith("Done.") and "https://example.com/attached-source" in reply


async def test_a_choice_card_alone_closes_the_stream_without_a_bubble(maker, monkeypatch):  # noqa: F811
    clarify = {"question": "Which one?", "options": [{"label": "A"}, {"label": "B"}]}

    async def run_native(**_kwargs):
        return {"final": None, "clarify": clarify, "escalation": None, "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    events = []
    await arslan.handle_user_message("main", "question", events.append)
    end = next(e for e in events if e["type"] == "stream_end")
    async with db_session.AsyncSessionLocal() as db:
        stored = [m for m in (await db.execute(select(ArslanMessage))).scalars().all() if m.role == "arslan"]
    assert end["message_id"] is None
    assert stored[-1].content == "Which one?\n- A\n- B"
    assert any(e["type"] == "clarify_options" for e in events)
