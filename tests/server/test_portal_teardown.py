"""The bounded portal teardown: a hang becomes a named, seconds-long report.

WHAT THIS IS NOT: a root-cause fix. The CI traceback (run 33637526779 and the
one before it) pins the hang to anyio's own ``thread.join()`` in
``start_blocking_portal.__exit__`` — AFTER the fixture's own finally (dispose
engines, ``stop(cancel_remaining=True)``) has completed — with the line before
it an aiosqlite connection whose terminate() was cancelled by that stop, inside
SQLAlchemy's greenlet bridge, where the inner close is ``asyncio.shield``ed
and so outlives the cancellation. Two local reproductions of that shape came
back CLEAN (docs/tech-debt/aiosqlite_portal_hang_repro.py); the mechanism
that keeps the loop alive afterwards is NOT established.

WHAT THIS DOES, all of it provable here without the CI machine:

  1. before the portal is stopped, every task the TEST created (not the
     portal's own) is cancelled and then WAITED for, with a bound, so a
     shielded close gets to finish instead of being abandoned mid-terminate;
  2. whatever is still alive after that bound is NAMED — coroutine and the
     frame it is suspended in — which is the attribution the 120s timeout
     never gave us;
  3. the portal thread is joined with a bound; past it the thread is
     abandoned (it is a daemon), counted, and reported in the terminal
     summary, instead of the whole suite sitting on it until pytest-timeout.

Half of this rests on CI evidence (the cancel-inside-terminate shape) and
half on none (that waiting is enough). The report in (2) is how we find out.
"""
import asyncio
import time

import pytest

from tests.server import portal_teardown
from tests.server.portal_teardown import drain_stragglers, shared_portal


@pytest.fixture(autouse=True)
def _leave_the_session_report_alone():
    """These tests provoke hangs on purpose. The session summary is for REAL
    ones — a line that prints on every run is a line nobody reads."""
    hangs, reports = portal_teardown._hangs, list(portal_teardown._reports)
    yield
    portal_teardown._hangs = hangs
    portal_teardown._reports[:] = reports


async def _stubborn_once():
    """Survives ONE cancellation, then dies on the next — the shape of a task
    that catches CancelledError to do some async cleanup."""
    try:
        await asyncio.sleep(100)
    except asyncio.CancelledError:
        await asyncio.sleep(100)


async def _immortal():
    """Survives EVERY cancellation. asyncio.run's own shutdown cancels once and
    gathers: this task never finishes, so the loop never dies and the thread
    never joins — the observed failure mode, made deterministic."""
    while True:
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            continue


def test_a_cancellable_straggler_is_unwound_before_the_portal_stops():
    unwound = []

    async def polite():
        try:
            await asyncio.sleep(100)
        finally:
            unwound.append(True)

    before = portal_teardown.hang_count()
    with shared_portal(grace=1.0, join_timeout=5.0, settle=0.05) as p:
        p.call(lambda: asyncio.get_running_loop().create_task(polite()) and None)
    assert unwound == [True], "the straggler was not cancelled and unwound"
    assert portal_teardown.hang_count() == before
    assert portal_teardown.last_report() is None


def test_a_straggler_that_survives_cancel_is_named_not_waited_on_forever():
    before = portal_teardown.hang_count()
    t0 = time.monotonic()
    with shared_portal(grace=0.3, join_timeout=5.0, settle=0.05) as p:
        p.call(lambda: asyncio.get_running_loop().create_task(
            _stubborn_once(), name="stubborn") and None)
    elapsed = time.monotonic() - t0
    assert elapsed < 4.0, f"teardown took {elapsed:.1f}s"
    report = portal_teardown.last_report()
    assert report is not None
    assert "stubborn" in report and "_stubborn_once" in report
    assert "test_portal_teardown.py" in report, "the suspended frame is the attribution"
    # This one still dies on the second cancel (anyio's own shutdown), so the
    # thread joins: it is a straggler report, not a hang.
    assert portal_teardown.hang_count() == before


def test_a_loop_that_will_not_die_is_abandoned_after_the_bound_not_after_120s():
    before = portal_teardown.hang_count()
    t0 = time.monotonic()
    with shared_portal(grace=0.3, join_timeout=1.0, settle=0.05) as p:
        p.call(lambda: asyncio.get_running_loop().create_task(
            _immortal(), name="immortal") and None)
    elapsed = time.monotonic() - t0
    assert elapsed < 5.0, f"teardown took {elapsed:.1f}s — the bound did not hold"
    assert portal_teardown.hang_count() == before + 1
    report = portal_teardown.last_report()
    assert "immortal" in report and "1.0s" in report


async def test_tasks_alive_before_the_test_are_not_ours_to_cancel():
    """The portal's own sleeper must survive the drain, or stop() breaks."""
    async def sleeper():
        await asyncio.sleep(100)
    ours = asyncio.get_running_loop().create_task(sleeper(), name="theirs")
    baseline = set(asyncio.all_tasks())
    later = asyncio.get_running_loop().create_task(sleeper(), name="ours")
    stuck = await drain_stragglers(baseline, grace=0.5, settle=0.05)
    assert later.cancelled()
    assert not ours.done()
    assert stuck == []
    ours.cancel()


async def test_a_task_already_inside_a_shielded_close_is_let_finish_not_cancelled():
    """The CI shape: at drain time a task is INSIDE a shielded close. Cancel
    it and the outer exits while the inner runs on, which is the very state
    the hang was found in. Give it the settle window instead."""
    finished = []

    async def inner():
        await asyncio.sleep(0.2)
        finished.append(True)

    async def outer():
        await asyncio.shield(inner())

    baseline = set(asyncio.all_tasks())
    task = asyncio.get_running_loop().create_task(outer())
    await asyncio.sleep(0.01)
    stuck = await drain_stragglers(baseline, grace=1.0, settle=0.5)
    assert finished == [True], "the shielded inner close was not allowed to finish"
    assert not task.cancelled(), "it was cancelled instead of let finish"
    assert stuck == []


async def test_a_task_born_while_another_unwinds_is_waited_for_not_cancelled():
    """terminate() runs INSIDE the cancel: the close it shields is born after
    the sweep. One sweep only, so it gets the grace, not a cancel."""
    finished = []

    async def cleanup():
        await asyncio.sleep(0.2)
        finished.append(True)

    async def outer():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            await asyncio.shield(cleanup())
            raise

    baseline = set(asyncio.all_tasks())
    asyncio.get_running_loop().create_task(outer())
    await asyncio.sleep(0.01)
    stuck = await drain_stragglers(baseline, grace=1.0, settle=0.05)
    assert finished == [True], "the cleanup born during unwinding was cancelled"
    assert stuck == []


def test_the_shared_fixture_reports_in_the_terminal_summary_only_when_it_fired():
    assert portal_teardown.report() is None or "portal" in portal_teardown.report()
