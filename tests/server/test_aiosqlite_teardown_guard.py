"""The aiosqlite teardown guard: turn a wrong red light into an accurate report.

WHAT THIS IS NOT: a root-cause fix. Two candidate causes were investigated and
BOTH were eliminated by measurement, which is worth writing down so nobody
spends the afternoon on them again:

  * "a leaked engine collected after the loop closed" — disposing the engine
    does NOT prevent it (measured), and 156 test files create engines the same
    way while the flake hits one random test.
  * "pytest-asyncio leaves abandoned tasks running" — it does not; an abandoned
    task comes back `cancelled=True` in the next test (measured).

WHAT IS ESTABLISHED: the exception comes from aiosqlite's worker thread calling
`future.get_loop().call_soon_threadsafe(...)` after that loop has closed. The
result it is delivering has no receiver — the future's loop is gone and nothing
awaits it — so the delivery failing is not a fault in itself. What IS a fault
is that it exits the thread through `threading.excepthook`, which pytest
records as an ERROR against whichever unrelated test happens to be running.

Three release runs have been re-run by hand because of it, and worse, it has
been teaching us to read a red CI as "probably the flake" — which is how a real
failure gets waved through.

So the guard catches exactly that delivery failure, counts it, and reports it at
the end of the session. Nothing is hidden: if it fires, the summary says so,
with the count. Any other exception from that thread propagates untouched.
"""
import asyncio
import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.server import aiosqlite_guard

_SLOW = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<3000000)"
         " SELECT count(*) FROM c")


def _provoke(tmp_path, name: str) -> None:
    """The measured shape: a loop closed while the worker still owes a reply.

    Runs on its OWN loop rather than the test's, because pytest-asyncio cancels
    abandoned tasks on its loops — which is precisely why this flake is rare and
    was never reproducible from ordinary test code.
    """
    loop = asyncio.new_event_loop()

    async def body():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/name}")

        async def slow():
            async with engine.connect() as conn:
                await conn.execute(text(_SLOW))

        asyncio.ensure_future(slow())
        await asyncio.sleep(0.05)

    loop.run_until_complete(body())
    loop.close()
    time.sleep(1.0)          # let the worker get to its delivery


def test_the_guard_catches_a_delivery_into_a_closed_loop(tmp_path):
    """The probe proves itself: with the guard removed this reaches
    threading.excepthook, which is what pytest turns into a phantom ERROR."""
    escaped = []
    previous = threading.excepthook
    threading.excepthook = lambda a: escaped.append(a.exc_value)
    before = aiosqlite_guard.suppressed_count()
    try:
        _provoke(tmp_path, "guarded.db")
    finally:
        threading.excepthook = previous

    assert aiosqlite_guard.suppressed_count() > before, "the guard did not see it"
    assert escaped == [], f"it still escaped to the excepthook: {escaped}"


def test_the_guard_is_installed_by_conftest_import():
    assert aiosqlite_guard.is_installed() is True


def test_a_different_failure_in_the_same_worker_still_propagates():
    """The narrowness that keeps this from becoming a blanket mute.

    Exercises the GUARDED function itself. The first version of this started an
    unrelated thread and watched it raise — which passes whether the guard is
    narrow or swallows everything, because an unrelated thread never enters the
    guard at all (measured: mutating the guard to swallow indiscriminately kept
    it green).
    """
    import aiosqlite.core as core

    def boom(*a, **k):
        raise ValueError("a real bug in the worker")

    original = core._connection_worker_thread
    # Reinstall the guard around a function that fails for another reason.
    aiosqlite_guard._installed = False
    core._connection_worker_thread = boom
    try:
        aiosqlite_guard.install()
        with pytest.raises(ValueError, match="a real bug"):
            core._connection_worker_thread(None)
    finally:
        core._connection_worker_thread = original
        aiosqlite_guard._installed = True


def test_a_runtime_error_that_is_not_about_a_closed_loop_still_escapes():
    """RuntimeError alone is not the signature — the message is part of it."""
    assert aiosqlite_guard._is_closed_loop_delivery(
        RuntimeError("Event loop is closed")) is True
    assert aiosqlite_guard._is_closed_loop_delivery(
        RuntimeError("something else entirely")) is False
    assert aiosqlite_guard._is_closed_loop_delivery(ValueError("Event loop is closed")) is False


def test_the_count_is_reported_not_silently_dropped():
    """If it fires, the session summary has to say so — a suppressed error that
    nobody ever hears about is the thing this project calls a lie.

    Exercises the hook rather than grepping conftest for a name: the first
    version of this asserted the source contained "suppressed_count" and went
    red while the report was working perfectly, which is a test measuring how
    the code is spelled instead of what it does.
    """
    from tests.server import conftest

    written = []

    class _Reporter:
        def write_sep(self, *a, **k):
            written.append(("sep", a))

        def write_line(self, line, *a, **k):
            written.append(("line", line))

    # Force the reporting case rather than depending on whether the guard
    # happened to fire earlier in this session: the first version branched on
    # that, so a report() that always returned None simply took the other
    # branch and passed (measured).
    saved = aiosqlite_guard._suppressed
    try:
        aiosqlite_guard._suppressed = 3
        conftest.pytest_terminal_summary(_Reporter(), 0, None)
    finally:
        aiosqlite_guard._suppressed = saved

    lines = [text for kind, text in written if kind == "line"]
    assert any("aiosqlite" in ln for ln in lines), written
    assert any("3" in ln for ln in lines), "the count itself must be reported"


def test_the_report_is_silent_when_nothing_was_suppressed():
    """No noise on the overwhelming majority of runs."""
    saved = aiosqlite_guard._suppressed
    try:
        aiosqlite_guard._suppressed = 0
        assert aiosqlite_guard.report() is None
    finally:
        aiosqlite_guard._suppressed = saved


def test_installing_twice_does_not_stack_wrappers():
    """Two imports must not double-count — a wrong number in the summary would
    be worse than no number, and nobody would notice it was wrong."""
    import aiosqlite.core as core

    before = core._connection_worker_thread
    aiosqlite_guard.install()          # already installed by conftest
    aiosqlite_guard.install()
    assert core._connection_worker_thread is before
