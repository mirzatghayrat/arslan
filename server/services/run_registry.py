"""server/services/run_registry.py

In-flight run registry — the cancellation seam (S3-M1) and the conversation
sink registry (S3-M2).

`_dispatch_spawn` registers the asyncio.Task executing each Run, keyed by
run_id with a conversation index; `POST /runs/{id}/cancel` resolves the task
and cancels it. The CancelledError surfaces inside _dispatch_spawn, which
finalizes the Run as 'cancelled'. Process-local by design: a run only exists
in the process executing it (a run that died with a previous process is the
boot reaper's job — see run_reaper.mark_interrupted_runs).

S3-M2 sink registry: frames outlive any single socket. Each WS connection
attaches a sink (its queue-emit) per conversation; `make_emit(conversation_id)`
hands `_dispatch_spawn` a fan-out emit that delivers every frame to whatever
sinks are attached at that moment — zero sinks means frames drop here (the
RunRecorder journal still captures them via tee). Reattach contract: a
connecting socket must pair `journal_snapshots(conversation_id)` +
`attach_sink(...)` in ONE synchronous block (no await between) so a frame
broadcast concurrently is either in the snapshot or delivered live — never
both, never neither. `journal_snapshots` therefore stays synchronous.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

_tasks: dict[int, asyncio.Task] = {}
_by_conversation: dict[str, set[int]] = {}
_sinks: dict[str, set[Callable[[dict], None]]] = {}  # conversation -> live emit sinks
_recorders: dict[int, Any] = {}  # run_id -> RunRecorder (journal access for reattach)


def register(
    run_id: int, conversation_id: str, task: asyncio.Task, *, recorder: Any | None = None
) -> None:
    _tasks[run_id] = task
    _by_conversation.setdefault(conversation_id, set()).add(run_id)
    if recorder is not None:
        _recorders[run_id] = recorder


def unregister(run_id: int, conversation_id: str) -> None:
    _tasks.pop(run_id, None)
    _recorders.pop(run_id, None)
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


def attach_sink(conversation_id: str, sink: Callable[[dict], None]) -> None:
    _sinks.setdefault(conversation_id, set()).add(sink)


def detach_sink(conversation_id: str, sink: Callable[[dict], None]) -> None:
    """Idempotent: discard the sink; drop the conversation entry once empty."""
    sinks = _sinks.get(conversation_id)
    if sinks is None:
        return
    sinks.discard(sink)
    if not sinks:
        _sinks.pop(conversation_id, None)


def make_emit(conversation_id: str) -> Callable[[dict], None]:
    """Fan-out emit for _dispatch_spawn: delivers ev to every currently-attached
    sink. The sink set is snapshotted per call (a sink may detach mid-iteration)
    and each sink is isolated — a broken sink (dead socket) must not break the
    others or the dispatch. No sinks -> drop silently (journal has them via tee).
    """

    def _emit(ev: dict) -> None:
        for sink in tuple(_sinks.get(conversation_id, ())):
            try:
                sink(ev)
            except Exception:
                pass

    return _emit


def journal_snapshots(conversation_id: str) -> list[tuple[int, list[dict]]]:
    """SYNC: [(run_id, copy of the recorder journal's events)] for the
    conversation's active runs, ascending run_id. Runs without a registered
    recorder are skipped. Must stay synchronous — the reattaching caller pairs
    this atomically (no await between) with attach_sink so no frame is lost
    or duplicated across the snapshot/live boundary.
    """
    out: list[tuple[int, list[dict]]] = []
    for run_id in active_for(conversation_id):
        recorder = _recorders.get(run_id)
        if recorder is None:
            continue
        out.append((run_id, [ev for (_ts, ev) in recorder._events]))
    return out
