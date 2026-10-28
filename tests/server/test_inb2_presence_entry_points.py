"""INB2: which entry points count as "the user is present" (server/services/presence.py, an allowlist).

Present: the window's user_message, and the iPhone's chat.send, which the Bridge delivers on the same socket
as a user_message with source "phone". Not present: everything else, here a resumed task (the window's or
the Bridge's resume_task frame), a scheduled fire and a background job. A new entry point counts only once
its own PR adds it to presence.py.
"""
import types

import pytest

from server.orchestrator import arslan
from server.services import presence, run_registry, scheduler, task_context, task_service, turn_journal
from tests.server.conftest import build_ws_client


@pytest.fixture(autouse=True)
def _clean_registry():
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()
    yield
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="inb2_presence.db")


@pytest.fixture
def seen(monkeypatch):
    """What each entry point's turn reads, recorded where the turn would run."""
    record = []

    async def answer(conversation_id, content, emit, **kw):
        record.append(("user_message", kw.get("source"), presence.present()))
        emit({"type": "stream_end", "message_id": None})

    async def resume(task_id, version, conversation_id, emit, **kw):
        record.append(("resume_task", None, presence.present()))
        emit({"type": "stream_end", "message_id": None})
    monkeypatch.setattr(arslan, "handle_user_message", answer)
    monkeypatch.setattr(task_service, "resume_turn", resume)
    return record


def _until_stream_end(ws, limit=40):
    for _ in range(limit):
        if ws.receive_json().get("type") == "stream_end":
            return
    raise AssertionError("no stream_end")


@pytest.mark.parametrize("frame,expected", [
    ({"type": "user_message", "content": "hi"}, ("user_message", None, True)),
    ({"type": "user_message", "content": "hi", "source": "phone"}, ("user_message", "phone", True)),
    ({"type": "resume_task", "task_id": "t-1", "expected_version": 1}, ("resume_task", None, False)),
    ({"type": "resume_task", "task_id": "t-1", "expected_version": 1, "source": "phone"}, ("resume_task", None, False)),
], ids=["window-message", "phone-chat-send", "window-resume", "bridge-resume"])
def test_only_a_typed_message_from_the_window_or_the_phone_counts_as_present(app_client, seen, frame, expected):
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()                                    # history
        ws.send_json(frame)
        _until_stream_end(ws)
    assert seen == [expected]


async def test_a_scheduled_fire_is_not_present_even_when_started_from_a_present_turn(monkeypatch):
    """A fire runs a stored prompt with nobody there. "Fire now" from a present turn's code path still
    must not inherit the turn's presence, so the fire marks itself not present."""
    record = []

    async def body_runner(cid, prompt, emit, body, headless=False):
        return await body(None)

    async def fire_body(task):
        record.append(presence.present())
    monkeypatch.setattr(task_context, "execute_entry", body_runner)
    monkeypatch.setattr(scheduler, "_fire_body", fire_body)
    with presence.user_turn():
        await scheduler._fire(types.SimpleNamespace(id=1, conversation_id="s-1", name="daily", prompt="go"))
    assert record == [False]
