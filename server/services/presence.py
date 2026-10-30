"""Whether the user is present in this turn (v0.1.64, INB2): an allowlist, kept here and nowhere else.

A turn counts as present only when one of these entry points started it, because a person typed the
message that started it:

- the window's `user_message` frame (server/ws/arslan.py);
- the iPhone's `chat.send`, which the Bridge delivers on the same socket as a `user_message` with source
  "phone" (same place), when it arrives soon after it was sent (`typed_just_now`). A message typed while
  the Mac was offline waits on the phone and can arrive hours later, with nobody there (①iOS, #475 review).

Everything else reads "not present": background jobs (they start from a fresh context), scheduled fires,
resumed tasks (`resume_task`), every other frame the window or the Bridge sends, and any entry point added
later. A new entry point (a sub-session's run, SUB) counts as present only if its own PR adds it here on
purpose and it is reviewed; a sub-session's run inside a present turn is wrapped in `not_present()`, so it
never inherits its parent's presence. A quick question (Q1) is not a new entry point: the iPhone sends it as
a `chat.send`, so it reads present like any phone message. That is harmless: it has four read-only tools and
learns nothing (Q1 card), and once turned into a chat it is an ordinary conversation.

What reads it: "about you" memories Arslan writes take effect directly only in a present turn
(arslan/companion/memory.py, decide_write; INB2). It is never a permission for anything else.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

_PRESENT: ContextVar[bool] = ContextVar("user_present", default=False)


@contextmanager
def user_turn():
    """Around a turn an allowlisted entry point starts (see the module docstring)."""
    token = _PRESENT.set(True)
    try:
        yield
    finally:
        _PRESENT.reset(token)


@contextmanager
def not_present():
    """Around a run inside a present turn that is not the person's own turn (a sub-session's run)."""
    token = _PRESENT.set(False)
    try:
        yield
    finally:
        _PRESENT.reset(token)


def present() -> bool:
    return _PRESENT.get()


#: How long a message typed on the iPhone may take to reach the Mac and still be the user being there.
FRESH_FOR = timedelta(minutes=5)
#: How far apart the phone's clock and the Mac's may be, either way.
CLOCK_SKEW = timedelta(minutes=2)


def typed_just_now(frame: dict, now: datetime | None = None) -> bool:
    """Does this `user_message` frame start a turn the user is present for? From the window, yes. From the
    iPhone (source "phone"), only when its send time, `sent_at` (the envelope's `ts`, which the Bridge passes
    on), is at most FRESH_FOR old, give or take CLOCK_SKEW. A missing, unreadable or zone-less one is not
    present: until the Bridge passes it (Q1b), a phone turn is not present and its "about you" entries wait."""
    if frame.get("source") != "phone":
        return True
    try:
        sent = datetime.fromisoformat(str(frame.get("sent_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if sent.tzinfo is None:
        return False
    age = (now or datetime.now(timezone.utc)) - sent
    return -CLOCK_SKEW <= age <= FRESH_FOR + CLOCK_SKEW
