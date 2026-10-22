"""asyncio helpers the product code uses instead of the standard ones that can misbehave on Python 3.11."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import weakref
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)
#: Work we cancelled (a stop, the limit) and that is still running this long is logged: it holds its caller's
#: cleanup or a process (an MCP server, a browser) that should be gone.
STILL_RUNNING_WARN_S = 30.0
_disposing: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, set[asyncio.Task]] = weakref.WeakKeyDictionary()


def disposing() -> set[asyncio.Task]:
    """The disposals still running on this loop, held until done (a task nobody holds can be collected). One
    set per loop: a disposal left pending when its loop closed never reaches another loop's."""
    return _disposing.setdefault(asyncio.get_running_loop(), set())


async def within(awaitable: Awaitable[T], timeout: float | None, *,
                 dispose: Callable[[T], Awaitable[Any]] | None = None) -> T:
    """`asyncio.wait_for` without its Python 3.11 flaw (gh-86296): wait_for returns what it awaited and drops a
    cancellation that lands just as that completes, so a stop on a turn's path could be lost (#377).

    Otherwise what wait_for does:
    - None: the awaitable is awaited as it is, with no limit; a limit of 0 or less: it never starts.
    - The awaitable runs in a task of its own (so a checkpoint inside sees a clean cancel count, #377).
    - Past the limit it is cancelled once and waited for; cancelled, that is TimeoutError, otherwise what it
      ended with (a value it returned anyway, or its error).
    - A stop of the caller cancels it once and waits for its cleanup, but leaves at once on a further stop
      (a second cancel never cuts the work's cleanup short), and always ends in the caller's CancelledError.

    The one difference: a stop that lands as the work completes wins (wait_for returned the result and lost the
    stop). So does a stop the work swallowed or turned into an error. What it still ended with is never
    returned: a value goes to `dispose` when one is given (a session or a connection to close), an error is
    logged, and neither replaces the stop.
    """
    if timeout is None:
        return await awaitable
    task = asyncio.ensure_future(awaitable)
    if timeout <= 0:
        return await _past_the_limit(task, dispose)
    try:
        async with asyncio.timeout(timeout) as limit:
            return await asyncio.shield(task)
    except asyncio.CancelledError:
        # asyncio.timeout turns only its own cancel into TimeoutError: this one is the caller's stop.
        _stopped(task, dispose)
        await asyncio.wait({task})          # its cleanup runs to the end; a further stop leaves at once
        raise
    except TimeoutError:
        if not limit.expired():
            raise                           # the work's own TimeoutError
        return await _past_the_limit(task, dispose)


async def _past_the_limit(task: asyncio.Future, dispose) -> Any:
    if not task.done():
        task.cancel()
        _watch(task)
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            _stopped(task, dispose, cancel=False)     # cancelled once already: its cleanup is not cut
            raise
    if task.cancelled():
        raise TimeoutError
    return task.result()


def _stopped(task: asyncio.Future, dispose, *, cancel: bool = True) -> None:
    """The caller was stopped: cancel the work once; whatever it still ends with is not returned."""
    if cancel and not task.done():
        task.cancel()
        _watch(task)

    def settled(done: asyncio.Future) -> None:
        if done.cancelled():
            return
        error = done.exception()
        if error is not None:
            logger.debug("work stopped by its caller ended with %s: %s", type(error).__name__, error)
        elif dispose is not None:
            closing = asyncio.ensure_future(_dispose(dispose, done.result()))
            held = disposing()
            held.add(closing)
            closing.add_done_callback(held.discard)
    task.add_done_callback(settled)


def _watch(task: asyncio.Future) -> None:
    """A WARNING if the work we just cancelled is still running after STILL_RUNNING_WARN_S."""
    def still_running() -> None:
        if not task.done():
            logger.warning("work cancelled %.0f s ago is still running: %r", STILL_RUNNING_WARN_S, task)
    later = asyncio.get_running_loop().call_later(STILL_RUNNING_WARN_S, still_running)
    task.add_done_callback(lambda _done: later.cancel())


async def _dispose(dispose, value) -> None:
    try:
        await dispose(value)
    except Exception:  # noqa: BLE001 — closing what nobody will use never replaces the stop
        logger.warning("closing a result after a stop failed", exc_info=True)


async def close_connection(connection: tuple[asyncio.StreamReader, asyncio.StreamWriter]) -> None:
    """`dispose` for asyncio.open_connection: close a connection nobody will use."""
    writer = connection[1]
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
