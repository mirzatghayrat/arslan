"""Move-4 (single-loop stabilization): RunRecorder step ordering must tie-break by
event ARRIVAL order, not by close order.

Steps close at a DIFFERENT event than they start — a ``tool_call`` step closes at
``tool_result``, an ``escalation`` at ``escalation_resolved``, the ``dispatch`` at
``spawn_meta`` — all AFTER their start event. So ``seq = len(steps)`` (append/close
order) does not equal the order the steps' originating events streamed. Under the
single-loop refactor, back-to-back events collide on ``datetime.utcnow()``, so
``started_at`` ties are common; the tie-break must then be deterministic w.r.t. the
order events actually arrived, NOT the order steps happened to close.
"""
from datetime import datetime

from server.services.run_recorder import RunRecorder


def _rec() -> RunRecorder:
    return RunRecorder(
        run_id=1,
        started_at=datetime(2026, 7, 13, 0, 0, 0),
        route_ms=5,
        spawn_name="beauty-guru",
        spawn_id=7,
    )


def test_steps_tie_break_by_event_arrival_not_close_order():
    r = _rec()
    # All three step-START events share the SAME timestamp t1 -> started_at tie.
    t1 = datetime(2026, 7, 13, 0, 0, 1)
    t2 = datetime(2026, 7, 13, 0, 0, 2)
    t3 = datetime(2026, 7, 13, 0, 0, 3)
    t4 = datetime(2026, 7, 13, 0, 0, 4)
    # Arrival order of the START events: dispatch(stream_start) -> tool_call -> escalation.
    # But they CLOSE in the reverse order: escalation(t2) -> tool_call(t3) -> dispatch(t4).
    # Close-order tie-break would yield [escalation, tool_call, dispatch]; arrival wins.
    r._events = [
        (t1, {"type": "stream_start", "source": "spawn"}),                       # arrival 0 -> dispatch
        (t1, {"type": "tool_call", "tool": "search", "args_summary": "q"}),      # arrival 1 -> tool_call
        (t1, {"type": "escalation", "kind": "data", "need": "budget"}),          # arrival 2 -> escalation
        (t2, {"type": "escalation_resolved", "how": "asked", "detail": "", "why": ""}),
        (t3, {"type": "tool_result", "tool": "search", "ok": True, "summary": "5 hits"}),
        (t4, {"type": "spawn_meta", "spawn_name": "beauty-guru"}),
    ]

    steps = r._derive_steps("final answer")
    kinds = [s["kind"] for s in steps]

    # Arrival order wins the started_at tie — NOT close order.
    assert kinds == ["dispatch", "tool_call", "escalation"], kinds
    # seq is re-numbered densely 0..n and the transient ordering key is stripped.
    assert [s["seq"] for s in steps] == [0, 1, 2]
    assert all("order" not in s for s in steps)


def test_route_step_sorts_first_by_timestamp():
    """A routing step starts at the recorder's started_at (earliest), so it sorts
    before later steps regardless of tie-break — a sanity guard that the arrival
    tie-break does not disturb the primary started_at ordering."""
    r = _rec()
    t1 = datetime(2026, 7, 13, 0, 0, 1)
    t2 = datetime(2026, 7, 13, 0, 0, 2)
    r._events = [
        (t1, {"type": "routing", "spawn_name": "beauty-guru"}),
        (t1, {"type": "stream_start", "source": "spawn"}),
        (t2, {"type": "spawn_meta", "spawn_name": "beauty-guru"}),
    ]
    steps = r._derive_steps("out")
    # route started_at = recorder started_at (00:00:00) < dispatch start (t1) -> route first.
    assert [s["kind"] for s in steps] == ["route", "dispatch"]
    assert [s["seq"] for s in steps] == [0, 1]
