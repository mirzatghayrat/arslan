"""Bounded teardown for the shared test portal.

The shared ``portal`` fixture runs a test's DB seed, its TestClient and every
websocket on ONE event loop in ONE thread (see conftest). Tearing that down
is where the suite has hung: anyio's ``start_blocking_portal.__exit__`` ends
in an unbounded ``thread.join()``, and on loaded CI runners that join has sat
for the full 120 s pytest-timeout with 3800+ tests green and one ERROR that
names whichever test was last — a red that has taught people to re-run
instead of read.

The CI traceback establishes this much (runs 33637526779 and earlier): the
fixture's own finally had completed; ``stop(cancel_remaining=True)`` cancelled
a task that was inside SQLAlchemy's aiosqlite ``do_terminate``, whose inner
close is ``asyncio.shield``ed and so outlived the cancel. Why the loop then
never finishes is NOT established — two local reproductions came back CLEAN
(docs/tech-debt/aiosqlite_portal_hang_repro.py).

So this module does the three things that can be proven here:

  * ``drain_stragglers`` — cancel the tasks the test left running, then WAIT
    (bounded) for them and for anything they spawn while unwinding, so a
    shielded close finishes instead of being abandoned; name what is still
    alive after the bound, with the frame it is suspended in;
  * ``shared_portal`` — the fixture body: drain, dispose engines on the loop,
    ``stop(cancel_remaining=True)``, then join the thread WITH a bound; past
    it the (daemon) thread is abandoned and the event counted;
  * ``report`` — the terminal-summary line, so an abandoned thread is said
    out loud with its attribution, never silently absorbed.

None of it is the root fix. It turns a 120 s anonymous red into a few
seconds and a name; the name is how the root gets found.
"""
from __future__ import annotations

import asyncio
import io
import threading
import time
import warnings
from concurrent.futures import Future
from contextlib import contextmanager
from typing import Iterator

from anyio import run as _run_eventloop
from anyio.from_thread import BlockingPortal

DEFAULT_SETTLE = 0.5         # seconds a straggler gets to finish on its own
DEFAULT_GRACE = 3.0          # seconds a straggler gets to unwind after cancel
DEFAULT_JOIN_TIMEOUT = 10.0  # seconds the portal thread gets to die

_hangs = 0
_reports: list[str] = []


class PortalTeardownWarning(UserWarning):
    """Raised (as a warning) when the portal did not shut down cleanly."""


def hang_count() -> int:
    """How many portal threads this session has had to abandon."""
    return _hangs


def last_report() -> str | None:
    """The most recent teardown report (straggler or hang), if any."""
    return _reports[-1] if _reports else None


def report() -> str | None:
    """One summary line for ``pytest_terminal_summary``; None when clean."""
    if not _reports:
        return None
    return (f"portal teardown: {_hangs} thread(s) abandoned past the join bound, "
            f"{len(_reports)} report(s); last:\n{_reports[-1]}")


def _describe(task: asyncio.Task) -> str:
    """Name + coroutine + the frame it is suspended in — the attribution."""
    buf = io.StringIO()
    try:
        task.print_stack(limit=3, file=buf)
    except Exception as exc:  # pragma: no cover — never let the report itself fail
        buf.write(f"<stack unavailable: {exc!r}>")
    return f"task {task.get_name()!r} {task.get_coro()!r}\n{buf.getvalue().rstrip()}"


async def drain_stragglers(
    baseline: set[asyncio.Task], grace: float, settle: float = DEFAULT_SETTLE,
) -> list[str]:
    """Three phases, each bounded, over every live task not in ``baseline``
    (and not this one):

      1. settle — wait up to ``settle`` for them to finish on their own. A
         task already inside a shielded connection close (the CI shape) is
         milliseconds from done; cancelling it is what we are trying to stop
         doing. Costs nothing when there are no stragglers.
      2. cancel — ONE sweep over the survivors. Not repeated: a task born
         while another unwinds (a shield's inner close, spawned by
         terminate()) must be waited for, never cancelled.
      3. grace — wait up to ``grace`` for everything, newborns included.

    Returns a description of each task still alive at the end (empty when
    the drain was clean)."""
    me = asyncio.current_task()
    loop = asyncio.get_running_loop()

    def _others() -> list[asyncio.Task]:
        return [t for t in asyncio.all_tasks(loop)
                if t is not me and t not in baseline and not t.done()]

    async def _wait_until(deadline: float) -> list[asyncio.Task]:
        while True:
            pending = _others()
            if not pending:
                return []
            left = deadline - time.monotonic()
            if left <= 0:
                return pending
            await asyncio.wait(pending, timeout=left)

    survivors = await _wait_until(time.monotonic() + settle)
    for t in survivors:
        t.cancel()
    stuck = await _wait_until(time.monotonic() + grace)
    return [_describe(t) for t in stuck]


@contextmanager
def shared_portal(
    *, grace: float = DEFAULT_GRACE, join_timeout: float = DEFAULT_JOIN_TIMEOUT,
    settle: float = DEFAULT_SETTLE,
) -> Iterator[BlockingPortal]:
    """anyio's ``start_blocking_portal``, with the teardown this suite needs.

    Yields a portal carrying ``_test_engines`` (filled by ``build_ws_client``).
    On exit: drain the test's stragglers (bounded), dispose the engines ON the
    portal loop, stop the portal cancelling what is left, join the thread
    (bounded). A thread alive past the bound is abandoned — it is a daemon —
    and reported: as a warning on this test and in the terminal summary.
    """
    global _hangs
    ready: Future[BlockingPortal] = Future()

    async def run_portal() -> None:
        async with BlockingPortal() as portal_:
            ready.set_result(portal_)
            await portal_.sleep_until_stopped()

    def run_thread() -> None:
        if ready.set_running_or_notify_cancel():
            try:
                _run_eventloop(run_portal)
            except BaseException as exc:  # pragma: no cover
                if not ready.done():
                    ready.set_exception(exc)

    thread = threading.Thread(target=run_thread, daemon=True, name="test-portal")
    thread.start()
    portal = ready.result()
    portal._test_engines = []  # type: ignore[attr-defined]
    baseline: set[asyncio.Task] = portal.call(lambda: set(asyncio.all_tasks()))
    try:
        yield portal
    finally:
        notes: list[str] = []
        try:
            stuck = portal.call(drain_stragglers, baseline, grace, settle)
            if stuck:
                notes.append(f"{len(stuck)} task(s) still alive {grace}s after cancel:\n"
                             + "\n".join(stuck))
            try:
                for engine in portal._test_engines:  # type: ignore[attr-defined]
                    portal.call(engine.dispose)
            finally:
                portal.call(portal.stop, True)
        finally:
            thread.join(join_timeout)
            if thread.is_alive():
                _hangs += 1
                notes.append(f"portal thread still alive {join_timeout}s after "
                             f"stop(cancel_remaining=True); abandoned (daemon).")
            if notes:
                text = "\n".join(notes)
                _reports.append(text)
                warnings.warn(PortalTeardownWarning(text), stacklevel=2)
