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

#: run_ids of the replays this attempt dispatched. Lives HERE rather than in replay_run
#: because the dispatcher must also be able to note one (a replay that RAISES has already
#: persisted its tokens on the Run row), and replay_run imports the dispatcher — so the
#: collector has to sit in a module neither of them owns.
_run_ids: ContextVar[list[int] | None] = ContextVar("evolution_run_ids", default=None)


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


@contextmanager
def collect_run_ids():
    """Gather the run_id of every replay dispatched on this task inside the block."""
    bucket: list[int] = []
    token = _run_ids.set(bucket)
    try:
        yield bucket
    finally:
        _run_ids.reset(token)


def note_run_id(run_id: int) -> None:
    """Record a replay run_id if a collection is active; a free no-op otherwise.

    🔴 Called from BOTH the success and the failure path. A replay that raises has
    already had `recorder.finalize` write its task_tokens to the Run row before the
    exception propagates — so if only the success path noted the id, those tokens would
    be burned, durable, and counted by nothing, while `actual` still reported
    `estimated: False`. evolution_loop swallows evaluator and gate failures and carries
    on, so an attempt can finish (even pass) with a slice of its cost invisible.
    """
    bucket = _run_ids.get()
    if bucket is not None and run_id not in bucket:
        bucket.append(run_id)


def note_failed_dispatch() -> None:
    """Mark that at least one replay arm raised. Its tokens are still counted (the id is
    noted either way), but the COUNTS may be short — a dispatch that died before
    reporting usage contributes 0 — so the attempt's numbers are flagged as estimates."""
    bump("failed_dispatches")
