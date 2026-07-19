"""Task-local call counters for one evolution attempt.

`EvolutionAttempt.estimate` projects five counters (pairs / dispatches / judge_calls /
optimizer_calls / synth_calls). To compare a projection against reality, reality has to
be counted — and counted where the calls actually happen, not inferred afterwards.

WHY A CONTEXTVAR AND NOT A RETURN VALUE. `propose_improvement` has six return statements
and three of them are early exits taken when something went wrong. Those are exactly the
attempts whose cost most needs to be visible ("we paid and got nothing"), and threading a
counter dict through six returns would be both invasive and easy to drop from the one
path that matters. A contextvar records from wherever the call is made, whichever way the
function leaves.

TASK-LOCAL, like usage_sink and replay_run's run-id collector, for the same reason:
skill_forge drives the same judge and gate code for the same spawn without the watcher's
concurrency guard, so a module-global counter would attribute its calls to whatever
evolution attempt happened to be running.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_counts: ContextVar[dict[str, int] | None] = ContextVar("evolution_counts", default=None)


@contextmanager
def counting():
    """Activate a fresh counter bucket for the duration of the block."""
    bucket: dict[str, int] = {}
    token = _counts.set(bucket)
    try:
        yield bucket
    finally:
        _counts.reset(token)


def bump(key: str, n: int = 1) -> None:
    """Record `n` occurrences of `key`. A free no-op when nothing is counting, so the
    call sites stay unconditional and cheap outside an attempt."""
    bucket = _counts.get()
    if bucket is not None:
        bucket[key] = bucket.get(key, 0) + n


def snapshot() -> dict[str, int]:
    return dict(_counts.get() or {})
