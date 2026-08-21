"""Stop aiosqlite's teardown race from being reported as somebody else's error.

THE FAULT IT ADDRESSES. aiosqlite's worker thread delivers each result with
``future.get_loop().call_soon_threadsafe(...)``. If that loop has closed in the
meantime, the call raises ``RuntimeError: Event loop is closed`` inside the
worker thread, which reaches ``threading.excepthook``, which pytest records as
an ERROR against whatever test is running at that moment — never the one that
caused it. Four sightings, four different tests, three hand re-runs of release
pipelines.

WHY SUPPRESSING THIS DELIVERY IS HONEST. The future's loop is closed, so nothing
is waiting for the result and nothing can be: the receiver is gone. The delivery
failing changes no outcome. What it does do is exit through the thread hook and
produce a red CI with zero failing tests — and a red that means "probably the
flake" is a red that stops meaning anything.

WHAT THIS IS NOT. It is not a root-cause fix, and it does not pretend to be:
the guard COUNTS what it catches and conftest reports the count in the session
summary. If the underlying race gets worse, the number goes up in the log
rather than disappearing. Two candidate root causes were eliminated by
measurement first — see the test module.

NARROW BY CONSTRUCTION: only a RuntimeError whose message is exactly about a
closed loop, only from aiosqlite's own worker function. Every other exception
from that thread propagates exactly as before.
"""
from __future__ import annotations

import threading

_suppressed = 0
_lock = threading.Lock()
_installed = False


def _is_closed_loop_delivery(exc: BaseException) -> bool:
    return isinstance(exc, RuntimeError) and "event loop is closed" in str(exc).lower()


def suppressed_count() -> int:
    with _lock:
        return _suppressed


def is_installed() -> bool:
    return _installed


def install() -> None:
    """Wrap aiosqlite's worker so a doomed delivery is counted, not raised.

    Idempotent: importing this module from more than one place must not stack
    wrappers, which would make the count wrong in a way nobody would notice.
    """
    global _installed
    if _installed:
        return

    import aiosqlite.core as core

    original = core._connection_worker_thread

    def guarded(*args, **kwargs):
        global _suppressed
        try:
            return original(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — re-raised unless it is THE one
            if not _is_closed_loop_delivery(exc):
                raise
            with _lock:
                _suppressed += 1
            return None

    core._connection_worker_thread = guarded
    _installed = True


def report() -> str | None:
    """A line for the session summary, or None when it never fired."""
    n = suppressed_count()
    if not n:
        return None
    return (f"aiosqlite teardown guard: suppressed {n} delivery/deliveries into a "
            f"closed event loop (no test outcome affected; see "
            f"tests/server/aiosqlite_guard.py)")
