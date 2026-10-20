"""S2a-1b: in a turn the iPhone started, a card only the Mac may approve never reaches the phone.

S2a-1 (decision U11) makes a card whose approved command would run with no sandbox window-only: a
phone Allow is swallowed, and the Mac bridge then refuses the phone's No too (it marked the card
answered). ①iOS's honest path, with no Bridge or frame change: don't send that card to the phone. The
phone's overview already counts the open approvals it does not hold, "另有 N 项只能在 Mac 上处理".

In a turn the iPhone started the turn runs on the Bridge's own socket, so the card skips exactly that
socket and still goes to every Mac window. A background job's cards go to every socket, where the
Bridge's cannot be told apart yet (v0.1.64: the Bridge socket says what it is).
"""
import pytest

from server.services import approvals, desktop_status, run_registry, turn_journal
from tests.server.conftest import build_ws_client
from tests.server.test_run_command_confirm_flow import (
    _collect_until,
    _enable_shell,
    _stub_run_command_executor,
    _stub_tool_loop_adapter,
)

PHONE_MESSAGE = {"type": "user_message", "content": "add a reminder", "source": "phone"}
BARE = ("osascript", ["-e", 'tell application "Reminders" to count lists'])          # runs bare once approved
WRAPPED = ("osascript", ["-e", 'tell application "Reminders" to delete every reminder'])   # stays wrapped


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
    client = build_ws_client(portal, tmp_path, monkeypatch, db_name="phone_mac_only.db")
    _enable_shell(client, policy="ask_risky")
    return client


def _types(frames):
    return [f.get("type") for f in frames]


def test_a_card_only_the_mac_may_approve_skips_the_phone_and_reaches_every_mac_window(app_client, monkeypatch):
    _stub_tool_loop_adapter(monkeypatch, *BARE)
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as other, \
            app_client.websocket_connect("/ws/arslan/main") as bridge:
        window.receive_json(), other.receive_json(), bridge.receive_json()          # history
        bridge.send_json(PHONE_MESSAGE)
        card = _collect_until(window, "propose_run_command")[-1]
        assert card["type"] == "propose_run_command" and approvals.window_only(card)
        assert _collect_until(other, "propose_run_command")[-1]["call_id"] == card["call_id"]
        # The phone's overview counts it: the island feed (status.waiting_approvals) holds the open card.
        assert desktop_status.island_feed()["awaiting"] == 1
        window.send_json({"type": "confirm_run_command", "call_id": card["call_id"], "scope": "once"})
        on_phone = _collect_until(bridge, "stream_end")
        assert "propose_run_command" not in _types(on_phone)                        # never on the phone
        assert len(executor.calls) == 1


def test_a_card_the_phone_may_answer_still_reaches_it(app_client, monkeypatch):
    """The usual cards of an iPhone turn are unchanged: on the phone and on every Mac window."""
    _stub_tool_loop_adapter(monkeypatch, *WRAPPED)
    _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as bridge:
        window.receive_json(), bridge.receive_json()
        bridge.send_json(PHONE_MESSAGE)
        on_phone = _collect_until(bridge, "propose_run_command")[-1]
        assert on_phone["type"] == "propose_run_command" and not approvals.window_only(on_phone)
        bridge.send_json({"type": "cancel_run_command", "call_id": on_phone["call_id"], "source": "phone"})
        _collect_until(bridge, "stream_end")
