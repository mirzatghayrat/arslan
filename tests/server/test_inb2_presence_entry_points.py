"""INB2: which entry points count as "the user is present" (server/services/presence.py, an allowlist).

Present: the window's user_message, and the iPhone's chat.send, which the Bridge delivers on the same socket
as a user_message with source "phone", when it arrives soon after it was sent (its `sent_at`; one that waited
on the phone while the Mac was offline is not the user being there, #475 review). Not present: everything
else, here a resumed task (the window's or the Bridge's resume_task frame), a scheduled fire and a background
job. A new entry point counts only once its own PR adds it to presence.py.
"""
import types
from datetime import datetime, timedelta, timezone

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


def _sent(minutes_ago: float) -> str:
    """A send time as the envelope's `ts` spells it (ISO 8601, UTC)."""
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


# The send times are made when the test runs, not when it is collected (LOAD4: in a 20-minute loaded run a
# "just sent" time made at collection was past FRESH_FOR + CLOCK_SKEW, 7 minutes, by the time it ran).
@pytest.mark.parametrize("frame,expected", [
    ({"type": "user_message", "content": "hi"}, ("user_message", None, True)),
    ({"type": "user_message", "content": "hi", "source": "phone", "sent_at": ("minutes ago", 0)},
     ("user_message", "phone", True)),
    ({"type": "user_message", "content": "hi", "source": "phone"}, ("user_message", "phone", False)),
    ({"type": "user_message", "content": "hi", "source": "phone", "sent_at": ("minutes ago", 60)},
     ("user_message", "phone", False)),
    ({"type": "resume_task", "task_id": "t-1", "expected_version": 1}, ("resume_task", None, False)),
    ({"type": "resume_task", "task_id": "t-1", "expected_version": 1, "source": "phone"}, ("resume_task", None, False)),
], ids=["window-message", "phone-chat-send", "phone-no-send-time", "phone-sent-an-hour-ago", "window-resume",
        "bridge-resume"])
def test_only_a_typed_message_from_the_window_or_the_phone_counts_as_present(app_client, seen, frame, expected):
    if isinstance(frame.get("sent_at"), tuple):
        frame = {**frame, "sent_at": _sent(frame["sent_at"][1])}
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


@pytest.mark.parametrize("minutes_ago,present", [(0, True), (6.9, True), (7.1, False), (-1.9, True), (-2.1, False)],
                         ids=["now", "just-inside", "too-old", "phone-clock-ahead", "too-far-ahead"])
def test_a_phone_message_counts_as_present_only_soon_after_it_was_sent(minutes_ago, present):
    """Five minutes on the way, and the two clocks may be two minutes apart either way."""
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    sent = (now - timedelta(minutes=minutes_ago)).isoformat()
    assert presence.typed_just_now({"source": "phone", "sent_at": sent}, now) is present


@pytest.mark.parametrize("sent_at", [None, "", "yesterday", "2026-10-29T12:00:00"],
                         ids=["missing", "empty", "unreadable", "no-time-zone"])
def test_a_phone_message_without_a_readable_send_time_is_not_present(sent_at):
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    assert presence.typed_just_now({"source": "phone", "sent_at": sent_at}, now) is False


def test_a_message_from_the_window_needs_no_send_time():
    assert presence.typed_just_now({"type": "user_message", "content": "hi"}) is True
