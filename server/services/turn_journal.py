"""In-flight orchestrator-turn journal — the thread-switch reattach seam.

Spawn runs survive a reconnect because RunRecorder journals their frames and
the WS attach block replays them (run_registry.journal_snapshots). Arslan's
OWN answer/tool turn had no journal: switching threads and back rendered a
blank pane while the turn kept running server-side, and although the
reattached sink delivered its live frames, the client discarded every one of
them for want of the stream_start preamble (arslanStore's
`if (!streaming) break` guards) — even the finished answer never landed.

This journal is that preamble. Per-conversation, in-memory, alive only while
a turn is in flight; the WS attach block replays it in the same synchronous
snapshot+attach window it already uses for run journals, so a concurrent
frame is either in the snapshot or delivered live — never both, never neither.

The tee journals ONLY the answer-turn frame vocabulary below. Spawn dispatch
inherits the caller's emit (arslan.py passes it straight down), so spawn-run
frames DO flow through the same tee — but those are already journaled by
their RunRecorder, and journaling them here too would replay them twice.
A whitelist (retain-semantics, like filter_replay_tools) fails safe: an
unknown new frame type is merely not replayed, never replayed twice.
"""
from __future__ import annotations

from typing import Callable

# The answer path's complete emit vocabulary (server/orchestrator/arslan.py
# _handle_answer_body + server/orchestrator/tool_loop.py run_native).
_TURN_FRAME_TYPES = frozenset(
    {"stream_start", "stream_chunk", "tool_call", "tool_result", "note", "stream_end"}
)

_active: dict[str, "TurnJournal"] = {}


class TurnJournal:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def tee(self, emit: Callable[[dict], None]) -> Callable[[dict], None]:
        """Wrap emit: every event still reaches emit; whitelisted ones are journaled."""

        def _tee(ev: dict) -> None:
            if ev.get("type") in _TURN_FRAME_TYPES:
                self.events.append(ev)
            emit(ev)

        return _tee


def begin(conversation_id: str) -> TurnJournal:
    journal = TurnJournal()
    _active[conversation_id] = journal
    return journal


def end(conversation_id: str, journal: TurnJournal) -> None:
    """Pop only our own journal — a racing begin() from another tab wins."""
    if _active.get(conversation_id) is journal:
        _active.pop(conversation_id, None)


def active(conversation_id: str) -> bool:
    return conversation_id in _active


def snapshot(conversation_id: str) -> list[dict]:
    """SYNC copy of the in-flight turn's events ([] when idle). Must stay
    synchronous: the WS attach block pairs it atomically with attach_sink."""
    journal = _active.get(conversation_id)
    return list(journal.events) if journal is not None else []
