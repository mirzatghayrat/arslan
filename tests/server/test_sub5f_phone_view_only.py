"""SUB5f, step 1 (the user, 2026-11-15): the phone views a sub-session and never talks to one, held on the Mac's side.

The phone reaches a conversation only through the Arslan Bridge, which opens `/ws/arslan/<id>` as a Mac window would
and marks what the phone sends there (`source: "phone"`). The Bridge links a conversation for a phone only once its
phone history answers, which a sub-session's never does (`phone._off_the_phone`), but this socket can't tell the
Bridge from a Mac window. So the socket holds the line too (`ws.arslan.phone_view_only`), in its reader, ahead of
everything a frame can do. On a sub-session's socket:
- a message from the phone is answered `SUB_SESSION_VIEW_ONLY`, stored nowhere, and starts no turn;
- it never reaches a turn already running there (K9b's steering);
- the phone's answer to a card asked there does nothing (a grandchild's card is asked in its parent, a sub-session).
A side chat (SIDE-1) is off the phone by the same lookup. Fails closed: a lookup that fails, or a sub-session's id whose
row can't say what it is now (none, or a delete's tombstone), counts as one.

Unchanged: the phone's messages anywhere else (a sub-session a delete's "keep" promoted is an ordinary chat), a window's
messages and answers in a sub-session (the Mac may talk to one), and the phone's answer to a child's card asked in the
commander's thread (`approvals.SubSessionAsker`).

Over the real socket and its reader, with K9b's scripted model and waiting tool.
"""
from __future__ import annotations

import asyncio

import pytest

from server.db.models import ArslanMessage
from server.services import approvals, run_registry, side_chats, steering, sub_sessions, turn_journal
from tests.server.conftest import build_ws_client
from tests.server.test_k9b_steering import STEER, _Model, _rows, _wire
from tests.server.test_run_command_confirm_flow import _collect_until

ROOT, KID, GRANDKID = "c-commander", "sub-kid", "sub-grandkid"
KEPT = "sub-kept"          # a sub-session a delete's "keep" promoted: an ordinary chat now
GHOST = "sub-ghost"        # a sub-session's id with no row
GONE = "sub-gone"          # a sub-session's id whose row is a delete's tombstone
SIDE = "side"              # the side chat the seed makes (its id is minted: MADE)
MADE: dict[str, str] = {}

PHONE_WORDS = "PHONE WORDS"
PHONE = {"type": "user_message", "content": PHONE_WORDS, "source": "phone"}
REFUSED = [("error", "SUB_SESSION_VIEW_ONLY")]
CARD = {"type": "propose_workspace_write", "call_id": "card-1", "action": "Write a file", "path": "notes.txt"}


@pytest.fixture(autouse=True)
def _clean():
    def reset():
        for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
            d.clear()
        turn_journal._active.clear()
        approvals._reset_for_tests()
        steering._open.clear()
        steering._taken.clear()
        sub_sessions._reset_for_tests()
        MADE.clear()
    reset()
    yield
    reset()


async def _seed(maker):
    async with maker() as db:
        db.add(ArslanMessage(conversation_id=ROOT, role="user", content="the commander's words"))
        await sub_sessions.create_child(db, ROOT, KID)
        await db.commit()
        await sub_sessions.create_child(db, KID, GRANDKID)
        kept = await sub_sessions.create_child(db, ROOT, KEPT)
        kept.kind, kept.parent_id, kept.sub_state = "chat", None, None          # as `sub_sessions._promote` leaves it
        await sub_sessions.tombstone(db, [GONE])
        await db.commit()
        MADE[SIDE] = (await side_chats.create(db, ROOT, None))["conversation_id"]


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, seed=_seed, db_name="sub5f.db")


def _until_probe(ws, cid: str) -> list[dict]:
    """What this socket is sent before the answer to a frame sent after the last one: its frames are handled in order,
    so whatever the frames before caused (a turn, a refusal) comes first. The probe changes nothing."""
    ws.send_json({"type": "session_ended", "conversation_id": cid})
    frames = _collect_until(ws, "session_ended_ack", max_frames=80)
    assert frames[-1]["type"] == "session_ended_ack", frames
    return frames[:-1]


def _codes(frames: list[dict]) -> list[tuple]:
    return [(f.get("type"), f.get("code")) for f in frames]


def _said(app_client, cid: str) -> list[tuple]:
    return [(role, content, source) for role, content, _run, source in _rows(app_client, cid)]


def _ask(app_client, asker) -> asyncio.Future:
    """A card asked through `asker`, waiting on the test client's loop."""
    async def start():
        return asyncio.ensure_future(asker(dict(CARD)))
    return app_client.portal.call(start)


def _decided(app_client, waiting: asyncio.Future) -> dict:
    async def wait():
        return await asyncio.wait_for(asyncio.shield(waiting), 5)
    return app_client.portal.call(wait)


@pytest.mark.parametrize("which", [KID, GRANDKID, SIDE, GHOST, GONE])
def test_a_phone_message_on_a_sub_sessions_socket_is_refused_stored_nowhere_and_starts_no_turn(
        app_client, monkeypatch, which):
    model = _Model()
    _wire(monkeypatch, model)
    cid = MADE.get(which, which)
    with app_client.websocket_connect(f"/ws/arslan/{cid}") as bridge:
        bridge.receive_json()                                         # history
        bridge.send_json(PHONE)
        frames = _until_probe(bridge, cid)
    assert _codes(frames) == REFUSED, frames
    assert _said(app_client, cid) == []
    assert model.inputs == []


@pytest.mark.parametrize("cid", [ROOT, KEPT, "c-new"])
def test_a_phone_message_anywhere_else_still_runs(app_client, monkeypatch, cid):
    model = _Model()
    _wire(monkeypatch, model)
    with app_client.websocket_connect(f"/ws/arslan/{cid}") as bridge:
        bridge.receive_json()
        bridge.send_json(PHONE)
        frames = _until_probe(bridge, cid)
    kinds = [f.get("type") for f in frames]
    assert "stream_end" in kinds and "error" not in kinds, frames
    assert ("user", PHONE_WORDS, "phone") in _said(app_client, cid)
    assert len(model.inputs) == 1


def test_a_window_message_in_a_sub_session_runs_as_before(app_client, monkeypatch):
    model = _Model()
    _wire(monkeypatch, model)
    with app_client.websocket_connect(f"/ws/arslan/{KID}") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "WINDOW WORDS"})
        frames = _until_probe(window, KID)
    kinds = [f.get("type") for f in frames]
    assert "stream_end" in kinds and "error" not in kinds, frames
    assert [said for said in _said(app_client, KID) if said[0] == "user"] == [("user", "WINDOW WORDS", None)]
    assert len(model.inputs) == 1


def test_a_phone_message_never_reaches_a_turn_running_in_the_sub_session(app_client, monkeypatch):
    model = _Model()
    tool = _wire(monkeypatch, model)
    with app_client.websocket_connect(f"/ws/arslan/{KID}") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "WANTS-TOOLS: two waits"})
        assert tool.started.wait(5)
        with app_client.websocket_connect(f"/ws/arslan/{KID}") as bridge:
            bridge.receive_json()
            bridge.send_json({"type": "user_message", "content": STEER, "source": "phone"})
            told = _until_probe(bridge, KID)        # after the running turn's replay (run_in_progress, its frames)
            tool.release.set()
            _collect_until(window, "stream_end", max_frames=80)
    assert REFUSED[0] in _codes(told) and ("queued", None) not in _codes(told), told
    assert tool.ran == ["a", "b"]                                     # nothing came in between the two calls
    assert not [given for given in model.inputs if STEER in given]
    assert [said for said in _said(app_client, KID) if said[0] == "user"] == [
        ("user", "WANTS-TOOLS: two waits", None)]


def test_on_a_sub_sessions_socket_the_phones_answer_does_nothing_and_a_windows_still_decides(app_client):
    with app_client.websocket_connect(f"/ws/arslan/{KID}") as bridge, \
            app_client.websocket_connect(f"/ws/arslan/{KID}") as window:
        bridge.receive_json(), window.receive_json()
        # A grandchild's card is asked in its parent's conversation, a sub-session (`approvals.SubSessionAsker`).
        waiting = _ask(app_client, approvals.SubSessionAsker(KID, GRANDKID))
        card = _collect_until(bridge, "propose_workspace_write")[-1]
        _collect_until(window, "propose_workspace_write")
        bridge.send_json({"type": "confirm_workspace_write", "call_id": card["call_id"], "source": "phone"})
        assert _until_probe(bridge, KID) == []                        # handled before the window answers below
        window.send_json({"type": "cancel_workspace_write", "call_id": card["call_id"]})
        decision = _decided(app_client, waiting)
    assert (decision["approved"], decision["by"]) == (False, "mac")


def test_the_phone_still_answers_a_childs_card_in_the_commanders_thread(app_client):
    with app_client.websocket_connect(f"/ws/arslan/{ROOT}") as bridge:
        bridge.receive_json()
        waiting = _ask(app_client, approvals.SubSessionAsker(ROOT, KID))
        card = _collect_until(bridge, "propose_workspace_write")[-1]
        assert card["sub_session"] is True
        bridge.send_json({"type": "confirm_workspace_write", "call_id": card["call_id"], "source": "phone"})
        decision = _decided(app_client, waiting)
    assert (decision["approved"], decision["by"]) == (True, "phone")


def test_a_lookup_that_fails_refuses_the_phone(app_client, monkeypatch):
    model = _Model()
    _wire(monkeypatch, model)

    async def unreadable(db, ids):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(sub_sessions, "sub_ids", unreadable)
    with app_client.websocket_connect(f"/ws/arslan/{ROOT}") as bridge:
        bridge.receive_json()
        bridge.send_json(PHONE)
        frames = _until_probe(bridge, ROOT)
    assert _codes(frames) == REFUSED, frames
    assert PHONE_WORDS not in [content for _role, content, _source in _said(app_client, ROOT)]
    assert model.inputs == []
