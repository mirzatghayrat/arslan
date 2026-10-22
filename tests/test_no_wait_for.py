"""No asyncio.wait_for in product code: `arslan.aio.within` instead (follow-up to #377).

Python 3.11's asyncio.wait_for returns what it awaited and drops a cancellation that lands just as that
completes (gh-86296). On a turn's path that is a lost stop: the turn runs on after the user pressed Stop
(#377 measured it on the model streams). `within` is wait_for without that: the same TimeoutError, the
awaitable in a task of its own as wait_for runs it, and no cancellation is ever lost.
"""
import asyncio
import pathlib
import re

import pytest

from arslan.aio import within

ROOT = pathlib.Path(__file__).resolve().parents[1]
#: ③Hands' files (docs/sessions.md: other lanes do not change them). DELETE-BY: v0.1.64, when ③Hands has
#: converted them; the entry goes with the last wait_for in the file.
NOT_YET = {"server/registry/hands_tools.py", "server/services/hands_client.py"}
_WAIT_FOR = re.compile(r"\basyncio\s*\.\s*wait_for\s*\(|from\s+asyncio\s+import[^\n]*\bwait_for\b")  # calls, not mentions


def test_no_product_code_uses_asyncio_wait_for():
    found = sorted(f"{path.relative_to(ROOT)}:{n}"
                   for base in ("server", "arslan")
                   for path in (ROOT / base).rglob("*.py")
                   if str(path.relative_to(ROOT)) not in NOT_YET
                   for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                   if _WAIT_FOR.search(line))
    assert found == [], "use arslan.aio.within, which never drops a cancellation"


def test_the_files_still_waiting_still_use_it():
    """When ③Hands converts one, its entry in NOT_YET goes too (so the list never outlives its reason)."""
    for name in NOT_YET:
        assert _WAIT_FOR.search((ROOT / name).read_text(encoding="utf-8")), name


async def test_within_returns_what_it_awaited():
    async def answer():
        await asyncio.sleep(0)
        return 42
    assert await within(answer(), 1) == 42
    assert await within(answer(), timeout=None) == 42


async def test_past_the_limit_it_raises_timeout_error_once_the_awaitable_has_stopped():
    stopped = []

    async def slow():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            stopped.append(True)
            raise
    with pytest.raises(TimeoutError):
        await within(slow(), 0.05)
    assert stopped == [True]


async def test_a_shielded_wait_lets_the_inner_work_go_on():
    inner = asyncio.ensure_future(asyncio.sleep(0.1, result="done"))
    with pytest.raises(TimeoutError):
        await within(asyncio.shield(inner), 0.01)
    assert not inner.cancelled() and await inner == "done"


async def _awaiting(fut):
    return await fut


@pytest.mark.timeout(20, method="thread")
@pytest.mark.parametrize("make", [lambda fut: fut, lambda fut: _awaiting(fut)], ids=["future", "coroutine"])
async def test_a_stop_that_lands_as_the_awaited_completes_is_not_lost(make):
    """asyncio.wait_for returns the result here and the stop is gone (gh-86296)."""
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    waiting = asyncio.create_task(within(make(fut), 60))
    await asyncio.sleep(0)
    loop.call_soon(fut.set_result, "answer")
    loop.call_soon(waiting.cancel)
    with pytest.raises(asyncio.CancelledError):
        await waiting


async def test_a_coroutine_runs_in_a_task_of_its_own_as_under_wait_for():
    """A stop lost elsewhere leaves the caller's task cancelling; TaskRuntime.checkpoint skips while its task
    is, so work awaited through `within` must not see that count (#377's review)."""
    caller = asyncio.current_task()
    caller.cancel()
    try:
        await asyncio.sleep(0)
    except asyncio.CancelledError:
        pass
    seen = []

    async def work():
        seen.append(asyncio.current_task().cancelling())
        return "ok"
    assert await within(work(), 60) == "ok"
    assert seen == [0]
    caller.uncancel()


async def test_what_finished_as_a_stop_landed_is_disposed_not_dropped():
    """The stop wins; a result that finished in that same moment is handed to `dispose` (a session, a
    connection), never silently dropped open."""
    gate = asyncio.Event()
    disposed = []

    async def opens():
        await gate.wait()
        return "connection"

    async def dispose(result):
        disposed.append(result)
    waiting = asyncio.create_task(within(opens(), 60, dispose=dispose))
    await asyncio.sleep(0)
    gate.set()
    await asyncio.sleep(0)                      # the work returns …
    waiting.cancel()                            # … and the stop lands before the waiter takes it
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert disposed == ["connection"]


@pytest.mark.parametrize("how", ["cut", "raised"])
async def test_nothing_is_disposed_when_the_work_did_not_finish(how):
    disposed = []

    async def dispose(result):
        disposed.append(result)

    async def work():
        if how == "raised":
            raise OSError("refused")
        await asyncio.sleep(10)
    with pytest.raises(OSError if how == "raised" else TimeoutError):
        await within(work(), 0.05, dispose=dispose)
    assert disposed == []
