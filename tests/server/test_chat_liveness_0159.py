"""0.1.59: a long answer is not "Interrupted", a second message waits its turn.

Seen on the user's Mac (run 160, 0.1.59-beta.3): the model spent ~5 minutes on one write_file and
the window said "Interrupted"; the follow-up started a second turn, was refused as a task conflict
("This item changed elsewhere") and lost. Spec: docs/specs/2026-10-11-0159-chat-liveness.md.
"""
import asyncio
import time

import pytest

from arslan.models import LLMResponse
from server.orchestrator import tool_loop as tool_loop_mod
from server.services import approvals, run_registry, turn_journal
from server.ws import arslan as ws_arslan
from tests.server.conftest import build_ws_client


@pytest.fixture(autouse=True)
def _clean_registry():
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    run_registry._no_replay.clear()
    turn_journal._active.clear()
    approvals._reset_for_tests()
    ws_arslan._turn_locks.clear()
    yield
    approvals._reset_for_tests()
    ws_arslan._turn_locks.clear()
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="chat_liveness.db")


class SlowFirstAdapter:
    """The first message takes a while (the long write); every other one answers at once."""

    def __init__(self, seconds: float):
        self.seconds, self.order = seconds, []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):  # noqa: ANN001
        text = str(user)
        if "first" in text:
            self.order.append("first:start")
            await asyncio.sleep(self.seconds)
            self.order.append("first:end")
            return LLMResponse(content="answer one", tool_calls=[], usage={})
        if "second" in text:
            self.order.append("second")
            return LLMResponse(content="answer two", tool_calls=[], usage={})
        return LLMResponse(content="ok", tool_calls=[], usage={})


@pytest.fixture
def slow(monkeypatch):
    adapter = SlowFirstAdapter(1.2)
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: adapter)
    return adapter


def _until(ws, predicate, max_frames=80):
    frames = []
    for _ in range(max_frames):
        f = ws.receive_json()
        frames.append(f)
        if predicate(f):
            return frames
    raise AssertionError(f"not seen in {max_frames} frames: {[x.get('type') for x in frames]}")


def _said(frames):
    return "".join(f.get("content") or "" for f in frames if f.get("type") == "stream_chunk")


def test_a_message_from_another_window_waits_its_turn_and_is_answered(app_client, slow):
    with app_client.websocket_connect("/ws/arslan/main") as w1, app_client.websocket_connect("/ws/arslan/main") as w2:
        w1.receive_json(), w2.receive_json()
        w1.send_json({"type": "user_message", "content": "first: draw the architecture"})
        _until(w2, lambda f: f.get("type") == "stream_start")          # the first turn is running
        w2.send_json({"type": "user_message", "content": "second: what does Interrupted mean?"})
        seen = _until(w2, lambda f: f.get("type") == "dequeued")
        assert "queued" in [f.get("type") for f in seen]
        rest = _until(w2, lambda f: f.get("type") == "stream_end")
        assert _said(rest) == "answer two"
        everything = seen + rest
        assert not [f for f in everything if f.get("type") == "error"], everything
    assert slow.order == ["first:start", "first:end", "second"]       # one turn at a time, in order
    with app_client.websocket_connect("/ws/arslan/main") as again:
        history = again.receive_json()["messages"]
    assert [m["content"] for m in history if m["role"] == "arslan"] == ["answer one", "answer two"]


def test_a_message_on_the_same_window_waits_too(app_client, slow):
    with app_client.websocket_connect("/ws/arslan/main") as w:
        w.receive_json()
        w.send_json({"type": "user_message", "content": "first: a long one"})
        _until(w, lambda f: f.get("type") == "stream_start")
        w.send_json({"type": "user_message", "content": "second: still there?"})
        waited = _until(w, lambda f: f.get("type") == "dequeued")
        kinds = [f.get("type") for f in waited]
        assert "queued" in kinds and kinds.index("queued") < kinds.index("stream_end")   # told while the first ran
        second = _until(w, lambda f: f.get("type") == "stream_end")
        assert _said(second) == "answer two"
        assert not [f for f in waited + second if f.get("type") == "error"]
    assert slow.order == ["first:start", "first:end", "second"]


def test_a_message_sent_right_after_the_answer_is_not_queued(app_client, slow, monkeypatch):
    """K2b, M3 #11: the first turn's post-turn work (looking for facts) is still running, and a
    message sent once the turn's lock is free starts at once, with no "queued". Before K2b the lock
    was held until the facts were looked for. (Sent the instant stream_end arrives, a message can
    still meet the turn's own last bookkeeping, a few milliseconds.)"""
    import threading

    from server.services import turn_facts
    slow.seconds = 0
    looking_done = threading.Event()
    # Before K2b the second message waits for this. Only a safety net, so a red run cannot hang: 30 s, not 4
    # (LOAD4: under load the two turns took longer than 4 s, the net fired first, and the last assert failed).
    fallback = threading.Timer(30, looking_done.set)

    async def _still_looking(conv, msg):
        while not looking_done.is_set():
            await asyncio.sleep(0.02)
        return []

    monkeypatch.setattr(turn_facts, "extract", _still_looking)
    fallback.start()
    try:
        with app_client.websocket_connect("/ws/arslan/main") as w:
            w.receive_json()
            w.send_json({"type": "user_message", "content": "first: hi"})
            _until(w, lambda f: f.get("type") == "stream_end")
            deadline = time.monotonic() + 10
            while ws_arslan._turn_lock("main").locked() and time.monotonic() < deadline:
                time.sleep(0.01)
            # The turn's lock is free while its facts are still being looked for.
            assert not ws_arslan._turn_lock("main").locked() and not looking_done.is_set()
            w.send_json({"type": "user_message", "content": "second: and now?"})
            frames = _until(w, lambda f: f.get("type") == "stream_end")
            assert "queued" not in [f.get("type") for f in frames]
            assert _said(frames) == "answer two"
            assert not looking_done.is_set()           # answered while the first turn's facts were looked for
    finally:
        looking_done.set()
        fallback.cancel()


def _recorded(conversation_id: str, seconds: float = 10.0) -> None:
    """Until the turn's run is registered and its journal holds something. The beats start with the turn, before
    it loads its context and registers its run, so under load the first beats come with nothing recorded yet
    (the app runs on the test client's portal thread; this one only reads the registry)."""
    deadline = time.monotonic() + seconds
    while not ((journals := run_registry.journal_snapshots(conversation_id)) and journals[0][1]):
        assert time.monotonic() < deadline, "the turn is recorded (so a beat could have been journaled)"
        time.sleep(0.01)


def test_still_working_beats_reach_the_window_and_are_never_replayed(app_client, slow, monkeypatch):
    monkeypatch.setattr(ws_arslan, "_WORKING_BEAT_S", 0.2)
    slow.seconds = 2.5
    with app_client.websocket_connect("/ws/arslan/main") as w:
        w.receive_json()
        w.send_json({"type": "user_message", "content": "first: a long one"})
        _until(w, lambda f: f.get("type") == "working")
        _recorded("main")
        with app_client.websocket_connect("/ws/arslan/main") as late:     # a window that re-attaches mid-turn
            late.receive_json()
            replay = _until(late, lambda f: f.get("type") in ("working", "stream_end"))
            # It hears a live beat, sent after the turn was recorded, but a beat is never part of the turn's
            # replayed journal.
            journals = run_registry.journal_snapshots("main")
            assert journals and journals[0][1], "the turn is still running"
            assert all(ev.get("type") != "working" for _run, events in journals for ev in events)
        _until(w, lambda f: f.get("type") == "stream_end", max_frames=400)    # five beats a second while it waited
    assert any(f.get("type") == "working" and f.get("elapsed_s", -1) >= 0 for f in replay)
