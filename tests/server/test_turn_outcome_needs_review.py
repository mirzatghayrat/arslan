"""A chat turn the loop stopped short of its answer reports "needs_review", not "ok".

The tool loop marks such a turn with its `stop_reason` (the work limit, the no-progress breaker, or a stream
the model ended after part of the answer was shown). The window's turn used to end with outcome "ok" anyway,
so the island and the phone said "done". Background jobs already end such a run as needs_review.
"""
import time

import pytest

from server.orchestrator import tool_loop
from server.services import desktop_status
from tests.server.test_run_command_confirm_flow import _collect_until, app_client  # noqa: F401 — fixture import


@pytest.fixture(autouse=True)
def fresh():
    desktop_status._reset_for_tests()
    yield
    desktop_status._reset_for_tests()


def _stub_loop(monkeypatch, stop_reason):
    async def fake_run_native(**kwargs):
        kwargs["on_chunk"]("Here is what I got to.")
        return {"final": "Here is what I got to.", "escalation": None, "tool_trace": [],
                "stop_reason": stop_reason, "history_compacted": False}
    monkeypatch.setattr(tool_loop, "run_native", fake_run_native)


def _turn_outcome(app_client):  # noqa: F811
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "do the long job"})
        _collect_until(ws, "stream_end")
        # stream_end comes before the turn reports itself: wait with the socket open (closing it cancels the turn).
        deadline = time.monotonic() + 10
        while (not any(e["kind"] == "turn_finished" for e in desktop_status.snapshot()["events"])
               and time.monotonic() < deadline):
            time.sleep(0.02)
    finished = [e for e in desktop_status.snapshot()["events"] if e["kind"] == "turn_finished"]
    assert len(finished) == 1, finished
    return finished[0]["outcome"]


@pytest.mark.parametrize("stop_reason", ["task_budget_exhausted", "task_no_progress", "model_error_after_text"])
def test_a_turn_the_loop_stopped_short_needs_review(app_client, monkeypatch, stop_reason):  # noqa: F811
    _stub_loop(monkeypatch, stop_reason)
    assert _turn_outcome(app_client) == "needs_review"


def test_a_turn_that_finished_its_answer_is_ok(app_client, monkeypatch):  # noqa: F811
    _stub_loop(monkeypatch, None)
    assert _turn_outcome(app_client) == "ok"
