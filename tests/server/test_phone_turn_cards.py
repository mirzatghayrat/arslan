"""Mobile bridge, Mac side: what the phone does shows up in the Mac's open windows.

- The phone's message appears live in a Mac window on the same conversation.
- A turn the phone started shows its confirmation cards on the phone (the Bridge's
  socket) AND in every Mac window; whoever answers first decides, and the other
  copy closes (`card_resolved`).
- A window's own turn keeps its card private, as before.

Two sockets on one conversation: `bridge` plays the Arslan Bridge (its user messages
carry source "phone"), `window` a Mac window. Harness and fakes from the run_command
confirm-flow suite.
"""
import pytest

from server.services import approvals, run_registry, turn_journal
from tests.server.conftest import build_ws_client
from tests.server.test_run_command_confirm_flow import (
    _collect_until,
    _enable_shell,
    _stub_run_command_executor,
    _stub_tool_loop_adapter,
)

PHONE_MESSAGE = {"type": "user_message", "content": "check the repo", "source": "phone"}


@pytest.fixture(autouse=True)
def _clean_registry():
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="phone_cards.db")


@pytest.fixture
def shell(app_client, monkeypatch):
    _enable_shell(app_client, policy="ask_all")
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    return _stub_run_command_executor(monkeypatch)


def _types(frames):
    return [f.get("type") for f in frames]


def test_the_phones_message_appears_live_in_an_open_mac_window(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as bridge:
        window.receive_json(), bridge.receive_json()            # history
        bridge.send_json(PHONE_MESSAGE)
        seen = _collect_until(window, "message")
        message = seen[-1]
        assert message["type"] == "message", _types(seen)
        assert (message["role"], message["content"], message["source"]) == ("user", "check the repo", "phone")
        assert isinstance(message["message_id"], int)
        card = _collect_until(bridge, "propose_run_command")[-1]
        bridge.send_json({"type": "cancel_run_command", "call_id": card["call_id"], "source": "phone"})
        _collect_until(bridge, "stream_end")


def test_a_window_message_is_not_echoed_as_a_message_frame(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as other:
        window.receive_json(), other.receive_json()
        window.send_json({"type": "user_message", "content": "check the repo"})
        window.send_json({"type": "cancel_run_command",
                          "call_id": _collect_until(window, "propose_run_command")[-1]["call_id"]})
        seen = _collect_until(other, "stream_end")
        assert "message" not in _types(seen)


def test_a_phone_turn_card_shows_on_both_and_the_mac_answers_first(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as bridge:
        window.receive_json(), bridge.receive_json()
        bridge.send_json(PHONE_MESSAGE)
        on_window = _collect_until(window, "propose_run_command")[-1]
        on_phone = _collect_until(bridge, "propose_run_command")[-1]
        assert on_window["type"] == on_phone["type"] == "propose_run_command"
        assert on_window["call_id"] == on_phone["call_id"]
        assert "background" not in on_window              # a foreground card: "remember" stays offered

        window.send_json({"type": "confirm_run_command", "call_id": on_window["call_id"]})
        resolved = _collect_until(bridge, "card_resolved")[-1]
        assert resolved == {"type": "card_resolved", "call_id": on_phone["call_id"],
                            "outcome": "approved", "by": "mac"}
        after = _collect_until(bridge, "stream_end")
        assert [f["ok"] for f in after if f.get("type") == "tool_result"] == [True]
        window_saw = _collect_until(window, "stream_end")
        assert "card_resolved" in _types(window_saw)
    assert len(shell.calls) == 1


def test_the_phone_answers_first_and_the_mac_card_closes(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as bridge:
        window.receive_json(), bridge.receive_json()
        bridge.send_json(PHONE_MESSAGE)
        card = _collect_until(bridge, "propose_run_command")[-1]
        bridge.send_json({"type": "cancel_run_command", "call_id": card["call_id"], "source": "phone"})
        seen = _collect_until(window, "card_resolved")
        assert seen[-1] == {"type": "card_resolved", "call_id": card["call_id"], "outcome": "declined", "by": "phone"}
        assert card["call_id"] in [f.get("call_id") for f in seen if f.get("type") == "propose_run_command"]
        after = _collect_until(bridge, "stream_end")
        assert [f["ok"] for f in after if f.get("type") == "tool_result"] == [False]
    assert shell.calls == []


def test_the_second_answer_is_swallowed_without_an_error_to_the_phone(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as bridge:
        window.receive_json(), bridge.receive_json()
        bridge.send_json(PHONE_MESSAGE)
        card = _collect_until(window, "propose_run_command")[-1]
        window.send_json({"type": "confirm_run_command", "call_id": card["call_id"]})
        _collect_until(bridge, "card_resolved")
        bridge.send_json({"type": "cancel_run_command", "call_id": card["call_id"], "source": "phone"})
        bridge.send_json({"type": "session_ended", "conversation_id": "elsewhere"})
        seen = _collect_until(bridge, "session_ended_ack")
        assert "error" not in _types(seen), seen
    assert len(shell.calls) == 1, "the late cancel must not undo the approval"


def test_a_window_turn_card_stays_private_to_that_window(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as other:
        window.receive_json(), other.receive_json()
        window.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(window, "propose_run_command")[-1]
        assert approvals.pending_cards("main") == [], "a window's own card is not a shared one"
        window.send_json({"type": "confirm_run_command", "call_id": card["call_id"]})
        _collect_until(window, "stream_end")
        seen = _collect_until(other, "stream_end")
        assert "propose_run_command" not in _types(seen) and "card_resolved" not in _types(seen)


def test_an_unanswered_phone_card_expires_on_both(app_client, shell, monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.3)
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as bridge:
        window.receive_json(), bridge.receive_json()
        bridge.send_json(PHONE_MESSAGE)
        card = _collect_until(bridge, "propose_run_command")[-1]
        assert _collect_until(bridge, "card_resolved")[-1] == {
            "type": "card_resolved", "call_id": card["call_id"], "outcome": "expired"}
        assert _collect_until(window, "card_resolved")[-1]["outcome"] == "expired"
        after = _collect_until(bridge, "stream_end")
        assert [f["ok"] for f in after if f.get("type") == "tool_result"] == [False]
    assert shell.calls == []


def test_when_the_bridge_drops_mid_card_the_mac_card_closes(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        with app_client.websocket_connect("/ws/arslan/main") as bridge:
            bridge.receive_json()
            bridge.send_json(PHONE_MESSAGE)
            card = _collect_until(bridge, "propose_run_command")[-1]
        seen = _collect_until(window, "card_resolved")
        assert seen[-1] == {"type": "card_resolved", "call_id": card["call_id"], "outcome": "expired"}
    assert shell.calls == []


async def test_the_first_answer_wins_even_when_both_arrive_before_the_turn_wakes():
    sent = []
    run_registry.attach_sink("c", sent.append)
    try:
        pending = approvals.open_card("c", {"type": "propose_run_command", "call_id": "k"})
        assert sent == [{"type": "propose_run_command", "call_id": "k"}]
        assert approvals.answer({"type": "confirm_run_command", "call_id": "k", "remember": True})
        assert approvals.answer({"type": "cancel_run_command", "call_id": "k", "source": "phone"}), \
            "the late reply is still recognised (and swallowed), not reported as unknown"
        assert approvals.close_card(pending) == {"approved": True, "remember": True, "by": "mac"}
        assert sent[-1] == {"type": "card_resolved", "call_id": "k", "outcome": "approved", "by": "mac"}
        assert approvals.pending_cards("c") == []
    finally:
        run_registry.detach_sink("c", sent.append)
