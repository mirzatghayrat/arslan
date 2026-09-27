"""What the desktop shell needs while its window is hidden (0.1.41).

The shell keeps the backend running after the window closes, shows a menu-bar
status, holds a sleep assertion while work is in flight and posts native
notifications. It learns all of that from this module, through one narrow,
authenticated loopback endpoint (`GET /api/v1/desktop/status`).

In-process state only: counts of work in flight and of confirmation cards that
are waiting, plus a short ring of notification events. Nothing here is
persisted; after a restart there is nothing to notify about. Events carry IDs
and an outcome, never message text, file content or source quotes — a
notification can be read on a locked screen.
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Iterator

KINDS = frozenset({"turn_finished", "approval_needed", "scheduled_finished", "scheduled_paused"})
OUTCOMES = frozenset({"ok", "error", "needs_review", "cancelled"})
MAX_EVENTS = 100

_lock = threading.Lock()
_events: deque[dict] = deque(maxlen=MAX_EVENTS)
_event_ids = itertools.count(1)
_tokens = itertools.count(1)
_working: dict[int, str | None] = {}
_awaiting: dict[int, str | None] = {}


def push(kind: str, *, conversation_id: str | None = None, outcome: str | None = None,
         task_id: int | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown desktop event kind: {kind}")
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError(f"unknown desktop event outcome: {outcome}")
    with _lock:
        event = {"id": next(_event_ids), "kind": kind, "conversation_id": conversation_id,
                 "outcome": outcome, "task_id": task_id, "at": int(time.time())}
        _events.append(event)
        return event


@contextmanager
def working(conversation_id: str | None = None) -> Iterator[None]:
    """Mark work in flight for as long as the block runs, however it exits."""
    with _lock:
        token = next(_tokens)
        _working[token] = conversation_id
    try:
        yield
    finally:
        with _lock:
            _working.pop(token, None)


@contextmanager
def awaiting_approval(conversation_id: str | None) -> Iterator[None]:
    """A confirmation card was SENT and is waiting for the user. Entered only
    after the card goes out, so an auto-approved action never notifies."""
    with _lock:
        token = next(_tokens)
        _awaiting[token] = conversation_id
    push("approval_needed", conversation_id=conversation_id)
    try:
        yield
    finally:
        with _lock:
            _awaiting.pop(token, None)


def snapshot(after: int = 0) -> dict:
    """Counts plus the events newer than `after`. `cursor` is the newest event
    id, so a client that starts with after=0 can skip history by adopting it."""
    with _lock:
        events = [dict(e) for e in _events if e["id"] > after]
        cursor = _events[-1]["id"] if _events else 0
        return {"cursor": cursor, "working": len(_working), "awaiting": len(_awaiting),
                "events": events}


def _reset_for_tests() -> None:
    global _event_ids
    with _lock:
        _events.clear()
        _working.clear()
        _awaiting.clear()
        _event_ids = itertools.count(1)
