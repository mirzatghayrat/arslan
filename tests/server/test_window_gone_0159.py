"""0.1.59: a turn survives its window's socket closing while it waits on a card.

Seen recording the promo on v0.1.59-beta.2: two long runs (19, 21) with many approval cards
ended "Model error", every step gone, error_kind HostError "Unexpected ASGI message
'websocket.send', after sending 'websocket.close'" — Arslan was in the background, its socket
had closed, and the next card was sent straight to it. The card is registered (the Inbox, the
island and a reconnected window can all answer it), so the turn now waits for that instead.
"""
import time

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
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="window_gone.db")


@pytest.fixture
def shell(app_client, monkeypatch):
    _enable_shell(app_client, policy="ask_all")
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    return _stub_run_command_executor(monkeypatch)


def _wait(predicate, seconds=10.0):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.02)


def _history_after(app_client):
    with app_client.websocket_connect("/ws/arslan/main") as again:
        return again.receive_json()


def test_the_window_closes_while_a_card_waits_and_the_inbox_answers_it(app_client, shell, monkeypatch):
    from starlette.websockets import WebSocket
    real, reads = WebSocket.receive_json, []

    async def receive_json(self, mode="text"):
        reads.append(1)
        return await real(self, mode)
    monkeypatch.setattr(WebSocket, "receive_json", receive_json)
    with app_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(window, "propose_run_command")[-1]
        window.close(1000)          # the app went to the background; its socket closed
        _wait(lambda: any(item["call_id"] == card["call_id"]
                          for item in app_client.get("/api/v1/approvals/pending").json()))
        before = len(reads)
        time.sleep(0.3)
        assert len(reads) - before <= 1, "a closed socket is not read again in a loop"
        assert app_client.post(f"/api/v1/approvals/{card['call_id']}/answer", json={"approve": True}).status_code == 200
        _wait(lambda: len(shell.calls) == 1)
        _wait(lambda: not run_registry.active_for("main"))
    history = _history_after(app_client)
    assert history["type"] == "history"
    assert [m for m in history["messages"] if m["role"] == "arslan" and m["content"]], "the answer was saved"


def test_a_window_that_reconnects_gets_the_waiting_card_and_answers_it(app_client, shell):
    with app_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(window, "propose_run_command")[-1]
        window.close(1000)
        _wait(lambda: approvals.pending_cards("main") != [])     # shared now that its window is gone
        with app_client.websocket_connect("/ws/arslan/main") as again:
            frames = _collect_until(again, "propose_run_command")
            assert frames[-1]["call_id"] == card["call_id"]
            again.send_json({"type": "confirm_run_command", "call_id": card["call_id"]})
            seen = _collect_until(again, "stream_end")
            assert "card_resolved" in [f.get("type") for f in seen]
    assert len(shell.calls) == 1


def test_a_card_sent_into_a_closed_socket_does_not_end_the_turn(app_client, shell, monkeypatch):
    """The exact production failure: uvicorn had already closed the socket, so the card's send
    raised — and from then on every send on that socket does."""
    from starlette.websockets import WebSocket
    real, closed = WebSocket.send_json, set()

    async def send_json(self, data, mode="text"):
        if id(self) in closed or (isinstance(data, dict) and data.get("type") == "propose_run_command"):
            closed.add(id(self))
            raise RuntimeError("Unexpected ASGI message 'websocket.send', after sending 'websocket.close'.")
        return await real(self, data, mode)
    monkeypatch.setattr(WebSocket, "send_json", send_json)
    with app_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "check the repo"})
        _wait(lambda: app_client.get("/api/v1/approvals/pending").json() != [])
        [listed] = app_client.get("/api/v1/approvals/pending").json()
        assert app_client.post(f"/api/v1/approvals/{listed['call_id']}/answer", json={"approve": True}).status_code == 200
        _wait(lambda: len(shell.calls) == 1)
        _wait(lambda: not run_registry.active_for("main"))
    history = _history_after(app_client)
    replies = [m["content"] for m in history["messages"] if m["role"] == "arslan"]
    assert replies and replies[-1] and "error" not in replies[-1].lower()


def test_a_card_nobody_answers_expires_and_the_turn_still_ends_cleanly(app_client, shell, monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.5)
    with app_client.websocket_connect("/ws/arslan/main") as window:
        window.receive_json()
        window.send_json({"type": "user_message", "content": "check the repo"})
        _collect_until(window, "propose_run_command")
        window.close(1000)
        _wait(lambda: not run_registry.active_for("main"))
    assert shell.calls == []                                  # nothing ran without a yes
    history = _history_after(app_client)
    assert any(m["role"] == "arslan" and m["content"] for m in history["messages"])
