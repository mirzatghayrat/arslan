"""The model this turn runs on, for tools that use the chat provider's own capabilities (0.1.63 D5).

Set around each executor call by tool_loop._dispatch_tool, beside the caller identity (tool_caller.py), from the
adapter _run_native resolved for the turn: the conversation's chosen model, or the vision slot when the turn
carries an image. web_search reads it to choose the model provider's own search, so a search goes to the party
THIS turn already talks to, never to whatever the primary config happens to be (before D5 it read the primary
config, so a conversation on a local model could send its queries to DeepSeek).

None means "not known": no provider's own search is used (fail-closed).
"""
from __future__ import annotations

import contextvars
from typing import Any

_current: contextvars.ContextVar[Any | None] = contextvars.ContextVar("turn_model", default=None)


def current() -> Any | None:
    """The turn's LLMAdapter, or None when no turn set one."""
    return _current.get()


def set_model(adapter: Any | None):
    """Returns a reset token; the caller MUST reset in finally."""
    return _current.set(adapter)


def reset_model(token) -> None:
    _current.reset(token)
