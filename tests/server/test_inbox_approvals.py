"""0.1.55 §12: every pending card is answerable from the Inbox (and later the island).

A window's own card stays private to that window (no copy in other windows, never
replayed into another tab) but is registered, so GET /approvals/pending lists it and
POST /approvals/{call_id}/answer decides it — through the same reply rule as the
socket: the reply is built from the card's own kind.
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
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="inbox_cards.db")


@pytest.fixture
def shell(app_client, monkeypatch):
    _enable_shell(app_client, policy="ask_all")
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    return _stub_run_command_executor(monkeypatch)


def _types(frames):
    return [f.get("type") for f in frames]


def test_a_window_card_is_listed_and_approved_from_the_inbox(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window, \
            app_client.websocket_connect("/ws/arslan/main") as other:
        window.receive_json(), other.receive_json()
        window.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(window, "propose_run_command")[-1]
        assert approvals.pending_cards("main") == [], "still private: never replayed into another tab"
        [listed] = app_client.get("/api/v1/approvals/pending").json()
        assert listed["call_id"] == card["call_id"] and listed["conversation_id"] == "main"
        assert listed["frame"]["type"] == "propose_run_command"
        assert listed["expires_at"] - listed["opened_at"] == approvals.TIMEOUT_S
        r = app_client.post(f"/api/v1/approvals/{card['call_id']}/answer", json={"approve": True})
        assert r.status_code == 200
        resolved = _collect_until(window, "card_resolved")[-1]
        assert resolved == {"type": "card_resolved", "call_id": card["call_id"], "outcome": "approved", "by": "inbox"}
        _collect_until(window, "stream_end")
        seen = _collect_until(other, "stream_end")
        assert "propose_run_command" not in _types(seen) and "card_resolved" not in _types(seen)
    assert len(shell.calls) == 1
    assert app_client.get("/api/v1/approvals/pending").json() == []


def test_declined_from_the_inbox_runs_nothing(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(window, "propose_run_command")[-1]
        assert app_client.post(f"/api/v1/approvals/{card['call_id']}/answer",
                               json={"approve": False}).status_code == 200
        assert _collect_until(window, "card_resolved")[-1]["outcome"] == "declined"
        _collect_until(window, "stream_end")
    assert shell.calls == []


def test_an_unknown_or_answered_card_is_404_and_a_stale_socket_reply_still_gets_busy(app_client, shell):
    assert app_client.post("/api/v1/approvals/nope/answer", json={"approve": True}).status_code == 404
    with app_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(window, "propose_run_command")[-1]
        window.send_json({"type": "confirm_run_command", "call_id": "stale-id"})
        busy = _collect_until(window, "error")[-1]
        assert busy["code"] == "BUSY"
        window.send_json({"type": "confirm_run_command", "call_id": card["call_id"]})
        _collect_until(window, "stream_end")
        assert app_client.post(f"/api/v1/approvals/{card['call_id']}/answer",
                               json={"approve": False}).status_code == 404
    assert len(shell.calls) == 1


def test_only_the_cards_own_kind_can_answer_it():
    """answer_by_id builds the reply from the card itself: it cannot be used to send
    some other kind of confirmation."""
    import asyncio

    async def go():
        pending = approvals.open_card("c", {"type": "propose_schedule", "call_id": "s1"}, broadcast=False)
        assert approvals.answer_by_id("s1", True, source="island")
        assert pending.future.result() == {"approved": True, "remember": False, "by": "island"}
        approvals.close_card(pending)
    asyncio.run(go())
