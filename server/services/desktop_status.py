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

import contextvars
import itertools
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Iterator
from urllib.parse import urlsplit

# lesson_learned (0.1.52 S5): quiet — the island counts it ("+1 practice"); no notification.
KINDS = frozenset({"turn_finished", "approval_needed", "scheduled_finished", "scheduled_paused", "proactive",
                   "lesson_learned"})
OUTCOMES = frozenset({"ok", "error", "needs_review", "cancelled"})
MAX_EVENTS = 100

_lock = threading.Lock()
_events: deque[dict] = deque(maxlen=MAX_EVENTS)
_event_ids = itertools.count(1)
_tokens = itertools.count(1)
_working: dict[int, str | None] = {}
_awaiting: dict[int, str | None] = {}

# Island (0.1.51 I1): what each run in flight is doing, and a title/summary per
# event. Kept APART from `_events`, which the status endpoint serves for
# notifications that can be read on a locked screen: those stay contentless.
# The island feed (an authenticated endpoint the on-screen island reads) is the
# only reader of these. Steps are minimal on purpose: a tool and a short target
# (a host, a file name, the start of a query or command), never full arguments.
_activity: dict[int, dict] = {}
_details: dict[int, dict] = {}
_current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("desktop_activity", default=None)
KINDS_OF_WORK = frozenset({"turn", "job", "scheduled"})
TARGET_CHARS = 40
TITLE_CHARS = 120
SUMMARY_CHARS = 160
PLAN_ITEM_CHARS = 60


def _clip(text, limit: int) -> str | None:
    if not isinstance(text, str):
        return None
    one_line = " ".join(text.split())
    return (one_line[: limit - 1] + "…" if len(one_line) > limit else one_line) or None


def push(kind: str, *, conversation_id: str | None = None, outcome: str | None = None,
         task_id: int | None = None, title: str | None = None, summary: str | None = None,
         work: str | None = None) -> dict:
    """`title`/`summary`/`work` reach the island feed only, never the status
    endpoint. `work` says which kind of run finished (KINDS_OF_WORK) where the
    event kind alone cannot: a chat turn and a background job both end in
    turn_finished, and the island treats them differently."""
    if kind not in KINDS:
        raise ValueError(f"unknown desktop event kind: {kind}")
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError(f"unknown desktop event outcome: {outcome}")
    if work is not None and work not in KINDS_OF_WORK:
        raise ValueError(f"unknown kind of work: {work}")
    with _lock:
        event = {"id": next(_event_ids), "kind": kind, "conversation_id": conversation_id,
                 "outcome": outcome, "task_id": task_id, "at": int(time.time())}
        _events.append(event)
        if title or summary or work:
            _details[event["id"]] = {"title": _clip(title, TITLE_CHARS), "summary": _clip(summary, SUMMARY_CHARS),
                                     "work": work}
        oldest = _events[0]["id"]
        for stale in [i for i in _details if i < oldest]:
            del _details[stale]
        return event


@contextmanager
def working(conversation_id: str | None = None, *, title: str | None = None,
            kind: str = "turn", job_id: str | None = None) -> Iterator[None]:
    """Mark work in flight for as long as the block runs, however it exits.
    The activity (title, latest step, plan) is reachable from inside the block
    through a context variable, so the tool loop can report steps without
    being handed anything."""
    if kind not in KINDS_OF_WORK:
        raise ValueError(f"unknown kind of work: {kind}")
    with _lock:
        token = next(_tokens)
        _working[token] = conversation_id
        activity = {"id": token, "conversation_id": conversation_id, "kind": kind,
                    "title": _clip(title, TITLE_CHARS), "started_at": int(time.time()),
                    "step": None, "plan": None,
                    # 0.1.55: lets the island's Stop end this job (POST /background-jobs/{id}/stop).
                    "job_id": job_id}
        _activity[token] = activity
    reset = _current.set(activity)
    try:
        yield
    finally:
        _current.reset(reset)
        with _lock:
            _working.pop(token, None)
            _activity.pop(token, None)


def step_target(tool: str, args: dict) -> str | None:
    """The one short thing a person needs to recognise a step: a host, a file
    name, or the start of a query or command. Never the full arguments."""
    if not isinstance(args, dict):
        return None
    if tool in ("web_extract", "browser_open"):
        host = urlsplit(str(args.get("url") or "")).hostname or ""
        return host[4:] if host.startswith("www.") else (host or None)
    if tool in ("read_file", "write_file", "edit_file", "list_dir"):
        return PurePosixPath(str(args.get("path") or "")).name or None
    if tool == "web_search":
        return _clip(args.get("query") or args.get("q"), TARGET_CHARS)
    if tool == "run_command":
        return _clip(args.get("command"), TARGET_CHARS)
    if tool.startswith("desktop_"):           # 0.1.53 Hands: the app and the element, never typed text
        thing = args.get("element") or args.get("keys") or ""
        return _clip(" · ".join(str(x) for x in (args.get("app"), thing) if x), TARGET_CHARS)
    return None


def note_step(tool: str, args: dict) -> None:
    """The run in flight just started a tool call. No-op outside `working`."""
    activity = _current.get()
    if activity is None or not isinstance(tool, str):
        return
    with _lock:
        activity["step"] = {"tool": tool, "target": step_target(tool, args), "at": int(time.time())}


def note_plan(items: list[dict]) -> None:
    """The run in flight changed its plan (update_plan). No-op outside `working`.
    The island shows the checklist itself, so items keep their status."""
    activity = _current.get()
    if activity is None:
        return
    kept = [{"text": _clip(i.get("text"), PLAN_ITEM_CHARS), "status": i.get("status")} for i in items]
    with _lock:
        activity["plan"] = {"items": kept,
                            "done": sum(1 for i in kept if i["status"] == "done"), "total": len(kept)}


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


def island_feed(after: int = 0) -> dict:
    """What the on-screen island shows: work in flight with its latest step and
    plan, cards waiting, and recent events with their title and summary."""
    with _lock:
        active = sorted(({**a, "step": dict(a["step"]) if a["step"] else None,
                          "plan": dict(a["plan"]) if a["plan"] else None} for a in _activity.values()),
                        key=lambda a: a["started_at"])
        events = [{**e, **_details.get(e["id"], {"title": None, "summary": None, "work": None})}
                  for e in _events if e["id"] > after]
        cursor = _events[-1]["id"] if _events else 0
        return {"cursor": cursor, "awaiting": len(_awaiting),
                "awaiting_conversations": sorted({c for c in _awaiting.values() if c}),
                "active": active, "events": events}


def _reset_for_tests() -> None:
    global _event_ids
    with _lock:
        _events.clear()
        _working.clear()
        _awaiting.clear()
        _activity.clear()
        _details.clear()
        _event_ids = itertools.count(1)
