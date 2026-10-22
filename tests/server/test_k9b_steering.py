"""K9b: a message sent mid-turn reaches the running turn at its next tool boundary (card K9; ⓪Plan's answers
in the K9 plan).

Over the real socket, reader and tool loop, with a scripted model and one fixture tool that waits for the test:
- the window: a message typed while a tool runs is read before the next call, which is not run (it still gets
  a result); the sender hears `dequeued` with `inserted`; the message is stored tagged with the run;
- the iPhone: a message from another socket (source "phone") reaches the turn running on the window's socket,
  is stored with its source, and the window is shown it;
- a turn already writing its answer has no boundary left: the message runs once, as the next turn;
- `steering_off` (DELETE-BY v0.1.64) leaves it waiting for the next turn, as before.
(A card waiting in the window keeps its rule, a typed message answers it No with the note and runs next:
test_window_permissions.py::test_a_message_typed_while_a_card_waits_answers_it, unchanged.)

And S3b's undo (⓪Plan's Q5): a steered turn is undone whole (its message and every message read mid-turn),
and a message read mid-turn is never counted as a turn of its own.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from arslan.models import LLMResponse
from server.db.models import ArslanMessage, Run
from server.orchestrator import arslan as arslan_mod
from server.orchestrator import memory
from server.orchestrator import tool_loop as tool_loop_mod
from server.services import approvals, run_registry, steering, turn_journal, turn_undo
from tests.server.conftest import build_ws_client
from tests.server.test_run_command_confirm_flow import _collect_until

STEER = "use the other folder instead"


@pytest.fixture(autouse=True)
def _clean():
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()
    approvals._reset_for_tests()
    steering._open.clear()
    yield
    approvals._reset_for_tests()
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()
    steering._open.clear()


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="k9b_steering.db")


def _call(name, args, call_id):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


class _Model:
    """A message with WANTS-TOOLS asks for two fixture_wait calls once; every later request answers. One with
    WANTS-SLOW answers after `slow_s` (no tools: the turn is writing its answer). Keeps what it was given.
    (Markers, not words: the turn's context around the message has words like "tools" in it.)"""

    def __init__(self, slow_s: float = 0.0):
        self.inputs: list[str] = []
        self.slow_s = slow_s
        self.writing = threading.Event()               # inside the slow answer

    async def chat(self, system, user, history=None, tools=None, temperature=0.7, **kwargs):
        self.inputs.append(json.dumps([*(history or []), {"role": "user", "content": user}],
                                      ensure_ascii=False, default=str))
        if len(self.inputs) == 1 and "WANTS-TOOLS" in str(user):
            return LLMResponse(content="", usage={}, tool_calls=[_call("fixture_wait", {"tag": "a"}, "c1"),
                                                                 _call("fixture_wait", {"tag": "b"}, "c2")])
        if "WANTS-SLOW" in str(user) and len(self.inputs) == 1:
            self.writing.set()
            await asyncio.sleep(self.slow_s)
        return LLMResponse(content=f"answer {len(self.inputs)}", tool_calls=[], usage={})


class _Wait:
    """A tool that runs until the test releases it."""

    def __init__(self):
        self.started, self.release, self.ran = threading.Event(), threading.Event(), []

    async def execute(self, args):
        self.ran.append(args.get("tag"))
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        return {"ok": True, "text": f"waited {args.get('tag')}"}


def _wire(monkeypatch, model):
    tool = _Wait()

    async def tools():
        return [{"key": "fixture_wait", "description": "Waits for the test."}]
    monkeypatch.setattr(arslan_mod, "_arslan_tools", tools)
    monkeypatch.setattr(arslan_mod, "_callable_tools", tools)
    monkeypatch.setitem(tool_loop_mod.EXECUTORS, "fixture_wait", tool)
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: model)
    return tool


def _rows(app_client, cid):
    async def read():
        async with app_client.db_maker() as db:
            return [(r.role, r.content, r.run_id, r.source) for r in (await db.execute(
                select(ArslanMessage).where(ArslanMessage.conversation_id == cid).order_by(ArslanMessage.id))).scalars()]
    return app_client.portal.call(read)


def _still(model, count, seconds=0.5):
    """Nothing more reaches the model for a moment (a message is never run twice)."""
    time.sleep(seconds)
    return len(model.inputs) == count


def test_the_window_a_message_typed_while_a_tool_runs_is_read_before_the_next_call(app_client, monkeypatch):
    model = _Model()
    tool = _wire(monkeypatch, model)
    with app_client.websocket_connect("/ws/arslan/k9b-window") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "WANTS-TOOLS: two waits"})
        assert tool.started.wait(5)
        ws.send_json({"type": "user_message", "content": STEER})
        before = _collect_until(ws, "queued")
        tool.release.set()
        frames = before + _collect_until(ws, "stream_end")
    assert {"type": "dequeued", "inserted": True} in frames
    assert tool.ran == ["a"]                                   # b was not started: the message came first
    second = json.loads(model.inputs[1])
    texts = [json.dumps(m, ensure_ascii=False) for m in second]
    at = next(i for i, t in enumerate(texts) if STEER in t)
    assert "Not run: the user sent a message" in "".join(texts[:at])    # b's result, before the message
    assert _still(model, 2)                                    # it did not run again as a turn of its own
    rows = _rows(app_client, "k9b-window")
    reply_run = next(run for role, _c, run, _s in rows if role == "arslan")
    assert [(role, content, run) for role, content, run, _s in rows if role == "user"] == [
        ("user", "WANTS-TOOLS: two waits", None), ("user", STEER, reply_run)]


def test_the_iphone_a_message_from_another_socket_reaches_the_turn_running_on_the_window(app_client, monkeypatch):
    model = _Model()
    tool = _wire(monkeypatch, model)
    with app_client.websocket_connect("/ws/arslan/k9b-phone") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "WANTS-TOOLS: two waits"})
        assert tool.started.wait(5)
        with app_client.websocket_connect("/ws/arslan/k9b-phone") as phone:
            phone.receive_json()
            phone.send_json({"type": "user_message", "content": STEER, "source": "phone"})
            assert {"type": "queued"} in _collect_until(phone, "queued")
            tool.release.set()
            seen = _collect_until(window, "stream_end", max_frames=80)
            told = _collect_until(phone, "dequeued", max_frames=80)
    assert told[-1] == {"type": "dequeued", "inserted": True}
    shown = [f for f in seen if f.get("type") == "message"]
    assert shown and shown[0]["content"] == STEER and shown[0]["source"] == "phone"
    assert STEER in model.inputs[1] and _still(model, 2)
    assert [(content, source) for role, content, _r, source in _rows(app_client, "k9b-phone") if role == "user"] == [
        ("WANTS-TOOLS: two waits", None), (STEER, "phone")]


def test_a_turn_writing_its_answer_has_no_boundary_the_message_runs_once_as_the_next_turn(app_client, monkeypatch):
    model = _Model(slow_s=1.0)
    _wire(monkeypatch, model)
    with app_client.websocket_connect("/ws/arslan/k9b-answer") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "WANTS-SLOW: one answer"})
        assert model.writing.wait(5)                   # the turn is writing its answer: no tool boundary left
        ws.send_json({"type": "user_message", "content": STEER})
        first = _collect_until(ws, "stream_end")
        second = _collect_until(ws, "stream_end")
    assert "queued" in [f.get("type") for f in first]
    assert {"type": "dequeued"} in second and {"type": "dequeued", "inserted": True} not in second
    assert len(model.inputs) == 2 and STEER in json.loads(model.inputs[1])[-1]["content"]
    assert _still(model, 2)
    assert [run for role, _c, run, _s in _rows(app_client, "k9b-answer") if role == "user"] == [None, None]


def test_steering_off_leaves_the_message_for_the_next_turn(app_client, monkeypatch):
    from server.services import settings_service

    async def off():
        async with app_client.db_maker() as db:
            await settings_service.update_settings(db, {"steering_off": "true"})
    app_client.portal.call(off)
    model = _Model()
    tool = _wire(monkeypatch, model)
    with app_client.websocket_connect("/ws/arslan/k9b-off") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "WANTS-TOOLS: two waits"})
        assert tool.started.wait(5)
        ws.send_json({"type": "user_message", "content": STEER})
        _collect_until(ws, "queued")
        tool.release.set()
        first = _collect_until(ws, "stream_end")
        second = _collect_until(ws, "stream_end")
    assert tool.ran == ["a", "b"] and {"type": "dequeued", "inserted": True} not in first + second
    assert len(model.inputs) == 3 and STEER not in model.inputs[1]


# ── S3b's undo, ⓪Plan's Q5 ─────────────────────────────────────────────────────────────────────────────

CID = "k9b-undo"


async def _turn(sessions, text, reply, *, steers=()):
    mid = await memory.add_message(CID, "user", text)
    async with sessions() as db:
        run = Run(conversation_id=CID, user_message=text, status="done", system_prompt="p")
        db.add(run)
        await db.commit()
        run_id = run.id
    for steer in steers:
        await memory.add_message(CID, "user", steer, run_id=run_id)
    async with sessions() as db:
        db.add(ArslanMessage(conversation_id=CID, role="arslan", content=reply, run_id=run_id))
        await db.commit()
    return SimpleNamespace(mid=mid, run=run_id)


async def _left(sessions):
    async with sessions() as db:
        return [r.content for r in (await db.execute(
            select(ArslanMessage).where(ArslanMessage.conversation_id == CID).order_by(ArslanMessage.id))).scalars()]


async def test_undoing_a_steered_turn_takes_its_message_and_every_message_read_mid_turn(execution_db):
    await _turn(execution_db, "plan the garden", "tomatoes")
    steered = await _turn(execution_db, "add herbs", "basil and mint", steers=["mint too"])
    shown = await turn_undo.preview(steered.run)
    assert (shown["conversation"], shown["later_turns"], shown["messages_after"]) == (True, 0, 3)
    out = await turn_undo.undo(steered.run)
    assert (out["later_turns"], out["messages"]) == (0, 3)
    assert await _left(execution_db) == ["plan the garden", "tomatoes"]


async def test_a_later_turns_message_read_mid_turn_is_not_a_turn_of_its_own(execution_db):
    first = await _turn(execution_db, "plan the garden", "tomatoes")
    await _turn(execution_db, "add herbs", "basil", steers=["and mint", "and chives"])
    assert (await turn_undo.preview(first.run))["later_turns"] == 1
    assert await memory.user_turn_count(CID) == 2                       # the turn clock counts turns


@pytest.mark.parametrize("steerable", [False, True], ids=["a job or a worker", "the chat turn"])
async def test_only_the_chat_turn_reads_the_box(execution_db, monkeypatch, steerable):
    """A job, a worker or a delegated loop on the same conversation never takes the user's message from
    the turn it was sent to (run_native's `steerable`, set by the chat turn only)."""
    cid, ran = "k9b-only-chat", []

    class Tool:
        async def execute(self, args):
            ran.append(args.get("tag"))
            if args.get("tag") == "a":                 # the message arrives while the first call runs
                steering.put(cid, steering.Steer(STEER, None, {"content": STEER}, told.append_async, lambda f: None))
            return {"ok": True, "text": "done"}

    class Told(list):
        async def append_async(self, frame):
            self.append(frame)
    told = Told()
    model = _Model()
    monkeypatch.setitem(tool_loop_mod.EXECUTORS, "fixture_wait", Tool())

    async def tools():
        return [{"key": "fixture_wait", "description": "Waits."}]
    steering.open_box(cid)
    try:
        await tool_loop_mod.run_native(system="S", user_content="WANTS-TOOLS", history=[], emit=lambda _: None,
                                       on_chunk=lambda _: None, resolve_tools=tools, adapter_override=model,
                                       conversation_id=cid, steerable=steerable)
        left = steering.take(cid)
    finally:
        steering._open.pop(cid, None)
    if steerable:
        assert ran == ["a"] and left == [] and told == [{"type": "dequeued", "inserted": True}]
        assert STEER in model.inputs[1]
    else:
        assert ran == ["a", "b"] and [s.content for s in left] == [STEER] and told == []
        assert STEER not in model.inputs[1]


@pytest.mark.parametrize("started,steered,origin", [(None, "phone", "chat"), ("phone", None, "phone")],
                         ids=["window turn, steered from the iPhone", "iPhone turn, steered from the window"])
async def test_a_turn_keeps_its_origin_whoever_steered_it(execution_db, started, steered, origin):
    """The runs list says where a turn came from by the message that started it, never one read mid-turn."""
    from server.api.runs import run_origins
    await memory.add_message(CID, "user", "the turn", source=started)
    async with execution_db() as db:
        run = Run(conversation_id=CID, user_message="the turn", status="done", system_prompt="p")
        db.add(run)
        await db.commit()
    await memory.add_message(CID, "user", "a steer", source=steered, run_id=run.id)
    async with execution_db() as db:
        db.add(ArslanMessage(conversation_id=CID, role="arslan", content="done", run_id=run.id))
        await db.commit()
        assert (await run_origins(db, [await db.get(Run, run.id)]))[run.id] == origin
