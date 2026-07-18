"""Caller identity for the tool-dispatch throat (brain-P2 Task 1).

Executors currently get only `execute(args)` — no identity of WHO is calling. This contextvar
carries that identity from the two run_native entry points (arslan.py's host answer path,
spawn_loop.py's spawn mini agent-loop) through tool_loop._dispatch_tool, so a later
memory-write executor can read `current_caller()` to enforce scope isolation.

None means "no caller was set" — a memory-write executor must treat that as fail-closed
(refuse the write) rather than guessing host vs. spawn."""
from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolCaller:
    actor: str            # "host" | "spawn"
    spawn_id: int | None  # None for host; the spawn's id for spawn actor
    conversation_id: str | None


_current: contextvars.ContextVar[ToolCaller | None] = contextvars.ContextVar(
    "tool_caller", default=None)


def current_caller() -> ToolCaller | None:
    """Executors read this to learn WHO is calling. None ⇒ no caller set ⇒ fail-closed
    (a memory-write executor must refuse rather than guess host/spawn)."""
    return _current.get()


def set_caller(caller: ToolCaller):
    """Returns a reset token; caller MUST reset in finally (zero residual pollution)."""
    return _current.set(caller)


def reset_caller(token) -> None:
    _current.reset(token)
