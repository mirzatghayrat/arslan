"""Whether the user is present in this turn (v0.1.64, INB2): an allowlist, kept here and nowhere else.

A turn counts as present only when one of these entry points started it, because a person typed the
message that started it:

- the window's `user_message` frame (server/ws/arslan.py);
- the iPhone's `chat.send`, which the Bridge delivers on the same socket as a `user_message` with source
  "phone" (same place).

Everything else reads "not present": background jobs (they start from a fresh context), scheduled fires,
resumed tasks (`resume_task`), every other frame the window or the Bridge sends, and any entry point added
later. A new entry point (Quick Ask, Q1; a sub-session's run, SUB) counts as present only if its own PR adds
it here on purpose and it is reviewed; a sub-session's run inside a present turn is wrapped in
`not_present()`, so it never inherits its parent's presence.

What reads it: "about you" memories Arslan writes take effect directly only in a present turn
(arslan/companion/memory.py, decide_write; INB2). It is never a permission for anything else.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

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
