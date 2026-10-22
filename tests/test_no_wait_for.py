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

from arslan import aio
from arslan.aio import within

ROOT = pathlib.Path(__file__).resolve().parents[1]
#: Files still waiting to be converted, with how many calls each still has; the count may only go down.
#: ③Hands converted its two (hands_tools.py, hands_client.py), so none is left. DELETE-BY: v0.1.64.
NOT_YET: dict[str, int] = {}
_IMPORT = re.compile(r"from\s+asyncio(?:\.tasks)?\s+import\s*(?:\([^)]*|[^\n]*)\bwait_for\b")


def _uses(text: str) -> int:
    """Calls of asyncio's wait_for however it is spelled (asyncio.wait_for, asyncio.tasks.wait_for, an alias
    of asyncio), plus imports of the name itself. Mentions in comments are not calls."""
    names = ["asyncio", *re.findall(r"^\s*import\s+asyncio\s+as\s+(\w+)", text, re.M)]
    call = re.compile(r"\b(?:" + "|".join(map(re.escape, names)) + r")\s*\.\s*(?:tasks\s*\.\s*)?wait_for\s*\(")
    return len(call.findall(text)) + len(_IMPORT.findall(text))


def test_no_product_code_uses_asyncio_wait_for():
    found = sorted(f"{path.relative_to(ROOT)}: {_uses(path.read_text(encoding='utf-8'))}"
                   for base in ("server", "arslan")
                   for path in (ROOT / base).rglob("*.py")
                   if str(path.relative_to(ROOT)) not in NOT_YET and _uses(path.read_text(encoding="utf-8")))
    assert found == [], "use arslan.aio.within, which never drops a cancellation"


def test_the_files_still_waiting_have_no_more_calls_than_counted():
    """A new call there fails too; when ③Hands converts one, its entry goes (the list never outlives it)."""
    assert {name: _uses((ROOT / name).read_text(encoding="utf-8")) for name in NOT_YET} == NOT_YET


@pytest.mark.parametrize("text,count", [
    ("x = await asyncio.wait_for(f(), 1)", 1),
    ("x = await asyncio.tasks.wait_for(f(), 1)", 1),
    ("x = await asyncio . wait_for (f(), 1)", 1),
    ("import asyncio as aio_\nx = await aio_.wait_for(f(), 1)", 1),
    ("from asyncio import wait_for", 1),
    ("from asyncio import (\n    gather,\n    wait_for,\n)", 1),
    ("from asyncio.tasks import wait_for as wf", 1),
    ("# Not asyncio.wait_for: it drops a cancel", 0),
    ("await condition.wait_for(predicate)", 0),
])
def test_the_guard_sees_every_spelling(text, count):
    assert _uses(text) == count


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
    await _disposals()
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
    await _disposals()
    assert disposed == []


async def _disposals():
    for _ in range(5):
        await asyncio.sleep(0)
    if aio._disposing:
        await asyncio.gather(*aio._disposing)


async def _stopped_twice(work, *, dispose=None, gap=0.05):
    """Start `within(work)`, stop it, then stop it again while its work cleans up."""
    waiting = asyncio.create_task(within(work, 60, dispose=dispose))
    await asyncio.sleep(0.02)
    waiting.cancel()
    await asyncio.sleep(gap)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting


async def test_a_second_stop_never_cuts_the_works_cleanup_short():
    """Review F1 of #384: wait_for cancelled the work once and left at once on a second cancel; the work's
    cleanup (an MCP stdio teardown, a browser's close) ran to its end."""
    cleaned = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.2)            # its cleanup, longer than the gap between the two stops
            cleaned.set()
            raise
    await _stopped_twice(work())                 # the caller leaves at once on the second stop …
    assert not cleaned.is_set()
    await asyncio.wait_for(cleaned.wait(), 5)    # … and the cleanup still runs to its end


async def test_a_stop_after_the_limit_never_cuts_the_works_cleanup_short():
    """Past the limit the work is cancelled once and its cleanup waited for; a stop then (a switch-off while an
    MCP start tears down after its budget) leaves at once and never cancels the work a second time."""
    cleaned = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.2)
            cleaned.set()
            raise
    waiting = asyncio.create_task(within(work(), 0.02))
    await asyncio.sleep(0.08)                    # past the limit, in the work's cleanup
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert not cleaned.is_set()
    await asyncio.wait_for(cleaned.wait(), 5)


@pytest.mark.parametrize("ending", ["returns a value", "raises an error"])
async def test_a_stop_the_work_swallows_or_turns_into_an_error_is_still_a_stop(ending):
    """Review F1 of #384: the caller's CancelledError, always; a value the work returned anyway is disposed."""
    disposed = []

    async def dispose(value):
        disposed.append(value)

    async def work():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            if ending == "returns a value":
                return "late"
            raise RuntimeError("cancel turned into an error") from None
    waiting = asyncio.create_task(within(work(), 60, dispose=dispose))
    await asyncio.sleep(0.02)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await _disposals()
    assert disposed == (["late"] if ending == "returns a value" else [])


async def test_a_dispose_that_fails_never_replaces_the_stop(caplog):
    """Review F2 of #384."""
    async def dispose(value):
        raise OSError("already closed")

    async def work():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return "late"
    waiting = asyncio.create_task(within(work(), 60, dispose=dispose))
    await asyncio.sleep(0.02)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await _disposals()
    assert "closing a result after a stop failed" in caplog.text


async def test_past_the_limit_a_value_the_work_returned_anyway_is_the_answer_as_with_wait_for():
    async def work():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return "anyway"
    assert await within(work(), 0.02) == "anyway"


async def test_no_limit_awaits_it_as_it_is_and_a_limit_of_zero_never_starts_it():
    """As wait_for: None awaits in the caller's own task; 0 or less cancels the work before it runs."""
    caller, seen, started = asyncio.current_task(), [], []

    async def where():
        seen.append(asyncio.current_task())
        return "ok"

    async def work():
        started.append(True)
        return "ran"
    assert await within(where(), None) == "ok" and seen == [caller]
    with pytest.raises(TimeoutError):
        await within(work(), 0)
    assert started == []
