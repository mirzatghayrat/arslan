"""server/services/run_registry.py

In-flight run registry — the cancellation seam (S3-M1).

`_dispatch_spawn` registers the asyncio.Task executing each Run, keyed by
run_id with a conversation index; `POST /runs/{id}/cancel` resolves the task
and cancels it. The CancelledError surfaces inside _dispatch_spawn, which
finalizes the Run as 'cancelled'. Process-local by design: a run only exists
in the process executing it (a run that died with a previous process is the
boot reaper's job — see run_reaper.mark_interrupted_runs).
"""
from __future__ import annotations

import asyncio

_tasks: dict[int, asyncio.Task] = {}
_by_conversation: dict[str, set[int]] = {}


def register(run_id: int, conversation_id: str, task: asyncio.Task) -> None:
    _tasks[run_id] = task
    _by_conversation.setdefault(conversation_id, set()).add(run_id)


def unregister(run_id: int, conversation_id: str) -> None:
    _tasks.pop(run_id, None)
    runs = _by_conversation.get(conversation_id)
    if runs is not None:
        runs.discard(run_id)
        if not runs:
            _by_conversation.pop(conversation_id, None)


def get(run_id: int) -> asyncio.Task | None:
    return _tasks.get(run_id)


def active_for(conversation_id: str) -> list[int]:
    return sorted(_by_conversation.get(conversation_id, set()))


def cancel(run_id: int) -> bool:
    """Cancel the live task for run_id. False when unknown or already finished."""
    task = _tasks.get(run_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True
