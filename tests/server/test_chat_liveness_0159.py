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


def test_still_working_beats_reach_the_window_and_are_never_replayed(app_client, slow, monkeypatch):
    monkeypatch.setattr(ws_arslan, "_WORKING_BEAT_S", 0.2)
    slow.seconds = 2.5
    with app_client.websocket_connect("/ws/arslan/main") as w:
        w.receive_json()
        w.send_json({"type": "user_message", "content": "first: a long one"})
        _until(w, lambda f: f.get("type") == "working")
        with app_client.websocket_connect("/ws/arslan/main") as late:     # a window that re-attaches mid-turn
            late.receive_json()
            replay = []
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                f = late.receive_json()
                replay.append(f)
                if f.get("type") in ("working", "stream_end"):
                    break
            # It hears the live beat, but a beat is never part of the turn's replayed journal.
            journals = run_registry.journal_snapshots("main")
            assert journals and journals[0][1], "the turn is recorded (so a beat could have been journaled)"
            assert all(ev.get("type") != "working" for _run, events in journals for ev in events)
        _until(w, lambda f: f.get("type") == "stream_end")
    assert any(f.get("type") == "working" and f.get("elapsed_s", -1) >= 0 for f in replay)
