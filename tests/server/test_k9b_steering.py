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
    steering._taken.clear()
    yield
    approvals._reset_for_tests()
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()
    steering._open.clear()
    steering._taken.clear()


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
            told = _collect_until(phone, "stream_end", max_frames=80)      # through the turn's own end
    assert {"type": "dequeued", "inserted": True} in told
    # Never echoed to its own sender: the Bridge would read the window's next turn as the phone's (review of #393).
    assert not [f for f in told if f.get("type") == "message"]
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


def _rows_reached(app_client, cid, wanted, seconds=8.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        rows = _rows(app_client, cid)
        if wanted(rows):
            return rows
        time.sleep(0.05)
    return _rows(app_client, cid)


@pytest.mark.parametrize("sender", ["window", "phone"])
def test_a_message_whose_socket_goes_before_the_turn_ends_still_runs_as_a_turn(app_client, monkeypatch, sender):
    """Review of #393: the turn was writing its answer (no boundary), and the sender's socket went meanwhile.
    Handed back at the turn's end it would land behind that socket's close and never run; it runs as a turn
    of its own, as a queued message always has. (A text frame that is not JSON is how the reader sees a socket
    go here: the test client cancels the endpoint when its context closes, which a real disconnect never does.)"""
    cid = f"k9b-gone-{sender}"
    model = _Model(slow_s=1.0)
    _wire(monkeypatch, model)

    def answered(rows):
        users = [i for i, row in enumerate(rows) if row[0] == "user" and row[1] == STEER]
        return bool(users) and any(row[0] == "arslan" for row in rows[users[0] + 1:])
    with app_client.websocket_connect(f"/ws/arslan/{cid}") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "WANTS-SLOW: one answer"})
        assert model.writing.wait(5)
        if sender == "window":
            window.send_json({"type": "user_message", "content": STEER})
            _collect_until(window, "queued")
            window.send_text("the socket went")
            rows = _rows_reached(app_client, cid, answered)
        else:
            with app_client.websocket_connect(f"/ws/arslan/{cid}") as phone:
                phone.receive_json()
                phone.send_json({"type": "user_message", "content": STEER, "source": "phone"})
                _collect_until(phone, "queued")
                phone.send_text("the socket went")
                rows = _rows_reached(app_client, cid, answered)
    assert answered(rows), rows
    assert [run for role, content, run, _s in rows if role == "user" and content == STEER] == [None]


def test_a_message_a_turn_took_and_never_sent_still_runs_when_its_socket_went_meanwhile(app_client, monkeypatch):
    """Review of #393: the window's turn took the phone's message after a tool, the phone's socket went, and the
    turn then ended without sending it (here its store failed). Handed back behind the socket's close it would
    never run; the closing socket waits for it, and it runs as a turn of its own."""
    cid = "k9b-taken-then-gone"
    model = _Model()
    tool = _wire(monkeypatch, model)
    committing, withdrawn, real_add, real_withdraw = threading.Event(), threading.Event(), memory.add_message, \
        steering.withdraw
    failed = []

    async def add_message(conversation_id, role, content, **kwargs):
        if content == STEER and not failed:
            failed.append(True)
            committing.set()
            while not withdrawn.is_set():               # the phone's socket goes now
                await asyncio.sleep(0.01)
            raise OSError("database is locked")
        return await real_add(conversation_id, role, content, **kwargs)

    def withdraw(conversation_id, inbox):
        mine = real_withdraw(conversation_id, inbox)
        withdrawn.set()
        return mine
    monkeypatch.setattr(memory, "add_message", add_message)
    monkeypatch.setattr(steering, "withdraw", withdraw)

    def answered(rows):
        users = [i for i, row in enumerate(rows) if row[0] == "user" and row[1] == STEER]
        return bool(users) and any(row[0] == "arslan" for row in rows[users[0] + 1:])
    with app_client.websocket_connect(f"/ws/arslan/{cid}") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "WANTS-TOOLS: two waits"})
        assert tool.started.wait(5)
        with app_client.websocket_connect(f"/ws/arslan/{cid}") as phone:
            phone.receive_json()
            phone.send_json({"type": "user_message", "content": STEER, "source": "phone"})
            _collect_until(phone, "queued")
            tool.release.set()
            assert committing.wait(5)                   # the turn took it, and is about to send it
            phone.send_text("the socket went")
            rows = _rows_reached(app_client, cid, answered)
    assert answered(rows), rows
    assert [(run, source) for role, content, run, source in rows if role == "user" and content == STEER] == [
        (None, "phone")]


def test_a_message_waiting_for_the_lock_leaves_the_running_turns_box_alone(app_client, monkeypatch):
    """The box opens only once a turn holds the lock: a message with an attachment (which waits for its own
    turn, on another socket) never replaces the running turn's box and what is in it."""
    cid = "k9b-lock-order"
    model = _Model()
    tool = _wire(monkeypatch, model)
    with app_client.websocket_connect(f"/ws/arslan/{cid}") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "WANTS-TOOLS: two waits"})
        assert tool.started.wait(5)
        window.send_json({"type": "user_message", "content": STEER})
        _collect_until(window, "queued")
        with app_client.websocket_connect(f"/ws/arslan/{cid}") as phone:
            phone.receive_json()
            phone.send_json({"type": "user_message", "content": "and this file", "attached_context": "notes"})
            _collect_until(phone, "queued")
            time.sleep(0.2)                           # the phone's own turn now waits for the lock
            tool.release.set()
            _collect_until(window, "stream_end", max_frames=80)
            _collect_until(phone, "stream_end", max_frames=80)
    assert STEER in model.inputs[1]                   # the running turn read it
    assert tool.ran == ["a"]


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


class _Told(list):
    async def __call__(self, frame):
        self.append(frame)


class _SteersIn:
    """fixture_wait: while its first call runs, the user sends a message (into the open box)."""

    def __init__(self, cid):
        self.cid, self.ran, self.told, self.inbox = cid, [], _Told(), asyncio.Queue()

    async def execute(self, args):
        self.ran.append(args.get("tag"))
        if args.get("tag") == "a":
            steering.put(self.cid, steering.Steer(STEER, None, {"type": "user_message", "content": STEER},
                                                  self.told, self.inbox))
        return {"ok": True, "text": f"done {args.get('tag')}"}


def _box_left(cid):
    left = [steer.content for steer in steering.take(cid)]
    steering._open.pop(cid, None)
    return left


@pytest.mark.parametrize("steerable", [False, True], ids=["a job or a worker", "the chat turn"])
async def test_only_the_chat_turn_reads_the_box(execution_db, monkeypatch, steerable):
    """A job, a worker or a delegated loop on the same conversation never takes the user's message from
    the turn it was sent to (run_native's `steerable`, set by the chat turn only)."""
    cid, model = "k9b-only-chat", _Model()
    tool = _SteersIn(cid)
    monkeypatch.setitem(tool_loop_mod.EXECUTORS, "fixture_wait", tool)

    async def tools():
        return [{"key": "fixture_wait", "description": "Waits."}]
    steering.open_box(cid)
    await tool_loop_mod.run_native(system="S", user_content="WANTS-TOOLS", history=[], emit=lambda _: None,
                                   on_chunk=lambda _: None, resolve_tools=tools, adapter_override=model,
                                   conversation_id=cid, steerable=steerable)
    left = _box_left(cid)
    if steerable:
        assert tool.ran == ["a"] and left == [] and tool.told == [{"type": "dequeued", "inserted": True}]
        assert STEER in model.inputs[1]
    else:
        assert tool.ran == ["a", "b"] and left == [STEER] and tool.told == []
        assert STEER not in model.inputs[1]


@pytest.mark.parametrize("path", ["a scheduled run", "a background job"])
async def test_a_turn_without_the_lock_never_takes_the_message(execution_db, monkeypatch, path):
    """Review of #393: a scheduled run (scheduler -> _handle_answer) and a job (background_body) run on the
    conversation without its turn lock: the message stays for the turn it was sent to."""
    cid, model = "k9b-no-lock", _Model()
    tool = _SteersIn(cid)
    monkeypatch.setitem(tool_loop_mod.EXECUTORS, "fixture_wait", tool)
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: model)

    async def tools():
        return [{"key": "fixture_wait", "description": "Waits."}]
    for name in ("_arslan_tools", "_callable_tools", "_background_tools", "_background_callable"):
        monkeypatch.setattr(arslan_mod, name, tools)
    steering.open_box(cid)
    if path == "a scheduled run":
        await arslan_mod._handle_answer(cid, "WANTS-TOOLS: scheduled", lambda _: None)
    else:
        await arslan_mod.background_body(cid, "WANTS-TOOLS: job", lambda _: None,
                                         SimpleNamespace(command=None, workspace_write=None, schedule=None))
    assert tool.ran == ["a", "b"] and _box_left(cid) == [STEER] and tool.told == []


class _Charged(_Model):
    """As a provider does: each request is counted against the budget as it is sent, and its tokens charged."""

    async def chat(self, system, user, history=None, tools=None, temperature=0.7, **kwargs):
        from arslan import execution_budget
        execution_budget.model_request(1024)
        response = await super().chat(system, user, history=history, tools=tools, temperature=temperature, **kwargs)
        execution_budget.charge_tokens(20)
        return response


@pytest.mark.parametrize("limit,model", [({"model_requests": 1}, _Model), ({"tokens": 12}, _Charged)],
                         ids=["its requests", "its tokens"])
async def test_a_message_read_that_no_request_carried_goes_back_to_run_on_its_own(execution_db, monkeypatch,
                                                                                  limit, model):
    """Review of #393: read after the batch, then the turn reaches a limit before the next request (the request
    count at the top of the step; tokens or dollars only as the provider sends it). The message is not stored
    and not said to be added; it goes back to its sender, to run once as a turn."""
    from arslan import execution_budget
    cid, model = "k9b-not-carried", model()
    tool = _SteersIn(cid)
    monkeypatch.setitem(tool_loop_mod.EXECUTORS, "fixture_wait", tool)

    async def tools():
        return [{"key": "fixture_wait", "description": "Waits."}]
    steering.open_box(cid)
    with execution_budget.scope(execution_budget.Budget(execution_budget.Limits(**limit))):
        await tool_loop_mod.run_native(system="S", user_content="WANTS-TOOLS", history=[], emit=lambda _: None,
                                       on_chunk=lambda _: None, resolve_tools=tools, adapter_override=model,
                                       conversation_id=cid, steerable=True)
    assert tool.ran == ["a"] and len(model.inputs) == 1                # read, then no request carried it
    assert tool.told == [] and _box_left(cid) == []
    assert tool.inbox.get_nowait() == {"type": "user_message", "content": STEER}
    async with execution_db() as db:
        assert (await db.execute(select(ArslanMessage).where(ArslanMessage.conversation_id == cid))).first() is None


@pytest.mark.parametrize("ending", ["a stop lands as it is stored", "its store fails"])
async def test_a_message_is_never_both_stored_and_handed_back(execution_db, monkeypatch, ending):
    """Review of #393: a stop that lands while the message is stored counts it as stored (handed back too, it
    would run twice); a store that fails hands it back, not stored (it runs once as a turn of its own)."""
    cid, model = "k9b-stored-once", _Model()
    tool = _SteersIn(cid)
    monkeypatch.setitem(tool_loop_mod.EXECUTORS, "fixture_wait", tool)
    stored, real = asyncio.Event(), memory.add_message

    async def add_message(conversation_id, role, content, **kwargs):
        if content != STEER:
            return await real(conversation_id, role, content, **kwargs)
        if ending == "its store fails":
            raise OSError("database is locked")
        message_id = await real(conversation_id, role, content, **kwargs)
        stored.set()
        await asyncio.sleep(10)                        # the stop lands here, the row already written
        return message_id
    monkeypatch.setattr(memory, "add_message", add_message)

    async def tools():
        return [{"key": "fixture_wait", "description": "Waits."}]
    steering.open_box(cid)
    turn = asyncio.create_task(tool_loop_mod.run_native(
        system="S", user_content="WANTS-TOOLS", history=[], emit=lambda _: None, on_chunk=lambda _: None,
        resolve_tools=tools, adapter_override=model, conversation_id=cid, steerable=True))
    if ending == "its store fails":
        with pytest.raises(OSError):
            await turn
    else:
        await asyncio.wait_for(stored.wait(), 5)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
    async with execution_db() as db:
        rows = (await db.execute(select(ArslanMessage.content).where(ArslanMessage.conversation_id == cid))).all()
    assert tool.told == [] and steering._taken == []
    if ending == "its store fails":
        assert rows == [] and tool.inbox.get_nowait() == {"type": "user_message", "content": STEER}
    else:
        assert [row.content for row in rows] == [STEER] and tool.inbox.empty()
    _box_left(cid)


async def test_a_reply_cut_off_keeps_every_calls_truncation_note_while_a_message_waits(execution_db, monkeypatch):
    """Review of #393: a reply cut by the output limit runs none of its calls and reads nothing after them; a
    waiting message never replaces a call's truncation note with "the message comes right after"."""
    cid = "k9b-cut-off"

    class _Cut(_Model):
        async def chat(self, system, user, history=None, tools=None, temperature=0.7, **kwargs):
            response = await super().chat(system, user, history=history, tools=tools, temperature=temperature,
                                          **kwargs)
            if len(self.inputs) == 1:
                response.finish_reason = "length"
            return response
    model, told = _Cut(), _Told()
    monkeypatch.setitem(tool_loop_mod.EXECUTORS, "fixture_wait", _SteersIn(cid))

    async def tools():
        return [{"key": "fixture_wait", "description": "Waits."}]
    steering.open_box(cid)
    steering.put(cid, steering.Steer(STEER, None, {"type": "user_message", "content": STEER}, told, asyncio.Queue()))
    await tool_loop_mod.run_native(system="S", user_content="WANTS-TOOLS", history=[], emit=lambda _: None,
                                   on_chunk=lambda _: None, resolve_tools=tools, adapter_override=model,
                                   conversation_id=cid, steerable=True)
    second = model.inputs[1]
    assert second.count("The output limit was reached") == 2 and "Not run: the user sent a message" not in second
    assert STEER not in second and _box_left(cid) == [STEER]


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


# ── on the wire: the native protocols (review of #393) ─────────────────────────────────────────────────

def _claude_reply(first: bool) -> bytes:
    from tests.llm.test_k8b_anthropic_stream import block, end, piece, sse, start, stop
    if not first:
        return sse(start(), block(0, {"type": "text", "text": ""}), piece(0, type="text_delta", text="Done."),
                   stop(0), end("end_turn"))
    events = [start()]
    for i, (call_id, tag) in enumerate((("toolu_1", "a"), ("toolu_2", "b"))):
        events += [block(i, {"type": "tool_use", "id": call_id, "name": "fixture_wait", "input": {}}),
                   piece(i, type="input_json_delta", partial_json=json.dumps({"tag": tag})), stop(i)]
    return sse(*events, end("tool_use"))


def _claude_whole(first: bool) -> dict:
    from tests.llm.test_k8b_anthropic_stream import whole
    if not first:
        return whole([{"type": "text", "text": "Done."}])
    return whole([{"type": "tool_use", "id": f"toolu_{i}", "name": "fixture_wait", "input": {"tag": tag}}
                  for i, tag in ((1, "a"), (2, "b"))], reason="tool_use")


def _openai_reply(first: bool) -> dict:
    if first:
        message = {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function", "function": {"name": "fixture_wait",
                                                                "arguments": json.dumps({"tag": tag})}}
            for i, tag in ((1, "a"), (2, "b"))]}
    else:
        message = {"role": "assistant", "content": "Done."}
    return {"id": "c", "object": "chat.completion", "model": "deepseek-chat",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if first else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


@pytest.mark.parametrize("protocol", ["anthropic", "openai-compatible"])
async def test_on_the_wire_each_call_keeps_its_result_and_the_message_follows_them(execution_db, monkeypatch, protocol):
    """The request after the batch, as the provider receives it: the call that ran and the call not run each
    answered under its own id (a mismatch would fall back to the legacy text protocol), then the message."""
    import httpx

    from arslan.llm.adapter import LLMAdapter
    from arslan.llm.providers.anthropic_provider import AnthropicProvider
    from arslan.llm.providers.openai_provider import OpenAIProvider
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    cid, bodies = f"k9b-wire-{protocol}", []
    tool = _SteersIn(cid)
    monkeypatch.setitem(tool_loop_mod.EXECUTORS, "fixture_wait", tool)

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        first = len(bodies) == 1
        if protocol == "openai-compatible":
            return httpx.Response(200, json=_openai_reply(first))
        if body.get("stream"):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_claude_reply(first))
        return httpx.Response(200, json=_claude_whole(first))
    if protocol == "anthropic":
        adapter = LLMAdapter("anthropic", "claude-opus-5-5", api_key="k", base_url="https://api.anthropic.com/v1")
        adapter._provider = AnthropicProvider("claude-opus-5-5", api_key="k", base_url="https://api.anthropic.com/v1",
                                              transport=httpx.MockTransport(handler))
    else:
        adapter = LLMAdapter("openai", "deepseek-chat", api_key="k", base_url="https://api.deepseek.com/v1")
        adapter._provider = OpenAIProvider(model="deepseek-chat", api_key="k", base_url="https://api.deepseek.com/v1",
                                           transport=httpx.MockTransport(handler))

    async def tools():
        return [{"key": "fixture_wait", "description": "Waits."}]
    steering.open_box(cid)
    await tool_loop_mod.run_native(system="S", user_content="question", history=[], emit=lambda _: None,
                                   on_chunk=lambda _: None, resolve_tools=tools, adapter_override=adapter,
                                   conversation_id=cid, steerable=True)
    _box_left(cid)
    assert tool.ran == ["a"] and len(bodies) == 2
    messages = bodies[1]["messages"]
    if protocol == "anthropic":
        last = messages[-1]
        assert last["role"] == "user"
        kinds = [(b["type"], b.get("tool_use_id")) for b in last["content"]]
        assert kinds[:3] == [("tool_result", "toolu_1"), ("tool_result", "toolu_2"), ("text", None)], kinds
        assert "Not run" in json.dumps(last["content"][1]) and STEER in last["content"][2]["text"]
    else:
        at = next(i for i, m in enumerate(messages) if m.get("tool_calls"))
        after = messages[at + 1:]
        assert [(m["role"], m.get("tool_call_id")) for m in after[:3]] == [
            ("tool", "call_1"), ("tool", "call_2"), ("user", None)], after
        assert "Not run" in str(after[1]["content"]) and STEER in str(after[2]["content"])
