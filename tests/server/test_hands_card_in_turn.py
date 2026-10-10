"""A Hands card raised inside a chat reply is answered from the window that asked (L3 pilot,
2026-10-10). Hands' cards went through `approvals.ask`, which waits without reading the socket; in a
chat turn nothing else reads it either, so the window's Allow (`confirm_action`, AskSlot) was never
read: the card expired after five minutes as declined, and the socket died on its keepalive. A
background job's cards still go through `approvals.ask` (the window's read loop answers those).

Hands is faked (the contract fixtures); the model is a script: one `desktop_look`, then an answer.
"""
import time
from unittest.mock import AsyncMock

import pytest

import server.orchestrator.tool_loop as tool_loop_mod
from server.registry import hands_tools
from server.services import approvals, hands_client, hands_service, run_registry, task_context, turn_journal
from tests.server.conftest import build_ws_client
from tests.server.test_hands_0153 import FakeHands
from tests.server.test_run_command_confirm_flow import _collect_until


class _LookThenAnswer:
    """One `desktop_look` at Notes, then a plain answer (native tool calling and the legacy text path)."""

    def __init__(self):
        self.did = False

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):  # noqa: ANN001
        if not self.did:
            self.did = True
            yield '{"tool": "desktop_look", "args": {"app": "Notes"}}'
        else:
            yield "looked"

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):  # noqa: ANN001
        from arslan.models import LLMResponse
        if not self.did:
            self.did = True
            return LLMResponse(content=None, usage={}, tool_calls=[
                {"id": "c1", "function": {"name": "desktop_look", "arguments": {"app": "Notes"}}}])
        return LLMResponse(content="looked", tool_calls=[], usage={})


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()
    approvals._reset_for_tests()
    monkeypatch.setattr(hands_service, "_dir", lambda: tmp_path / "hands")
    hands_service._reset_for_tests()
    hands_tools._grants.clear()
    hands_tools._inline.clear()
    yield
    approvals._reset_for_tests()
    hands_service._reset_for_tests()
    hands_tools._grants.clear()
    hands_tools._inline.clear()


@pytest.fixture
def hands(monkeypatch):
    fake = FakeHands()
    monkeypatch.setattr(hands_client, "call", fake.call)
    monkeypatch.setattr(hands_client, "available", lambda: True)
    return fake


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    client = build_ws_client(portal, tmp_path, monkeypatch, db_name="hands_card_in_turn.db")
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _LookThenAnswer())
    # As in the app with its memory store active: a chat turn runs as a task, bound to its
    # conversation (otherwise a look refuses before any card: no conversation to ask in).
    monkeypatch.setattr(task_context, "is_active", AsyncMock(return_value=True))
    return client


def test_the_window_that_asked_answers_a_hands_card_in_its_own_turn(app_client, hands, monkeypatch):
    # Short enough that the old behaviour (nobody reads the answer) fails fast instead of waiting 300 s.
    monkeypatch.setattr(approvals, "TIMEOUT_S", 5)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()                                            # history
        ws.send_json({"type": "user_message", "content": "what does my Notes window show?"})
        card = _collect_until(ws, "propose_action")[-1]
        assert card["kind"] == "desktop_look" and card["target"] == "Notes"
        ws.send_json({"type": "confirm_action", "call_id": card["call_id"]})
        after = _collect_until(ws, "stream_end", max_frames=80)
    results = [f for f in after if f.get("type") == "tool_result" and f.get("tool") == "desktop_look"]
    assert results and results[0]["ok"] is True, after
    assert hands.ops("snapshot") == ["snapshot"], "the look ran: the answer was read, not timed out"
    assert approvals.pending_cards("main") == []


def test_declining_in_the_window_declines_the_card(app_client, hands, monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 5)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "what does my Notes window show?"})
        card = _collect_until(ws, "propose_action")[-1]
        sent = time.monotonic()
        ws.send_json({"type": "cancel_action", "call_id": card["call_id"]})
        after = _collect_until(ws, "tool_result", max_frames=80)
        decided_in = time.monotonic() - sent
        _collect_until(ws, "stream_end", max_frames=80)
    assert after[-1]["tool"] == "desktop_look" and after[-1]["ok"] is False
    # Declined by the answer, not by the card running out (5 s): the window's reply was read.
    assert decided_in < 2, f"decided after {decided_in:.1f} s: the card expired, nobody read the answer"
    assert hands.ops("snapshot") == []
