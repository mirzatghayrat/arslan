"""asyncio helpers the product code uses instead of the standard ones that can misbehave on Python 3.11."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def within(awaitable: Awaitable[T], timeout: float | None, *,
                 dispose: Callable[[T], Awaitable[Any]] | None = None) -> T:
    """`asyncio.wait_for` without its Python 3.11 flaw (gh-86296): wait_for returns what it awaited and drops a
    cancellation that lands just as that completes, so a stop on a turn's path could be lost (#377).

    Otherwise the same: the awaitable runs in a task of its own (a coroutine is wrapped, a future is awaited
    as is), past `timeout` it is cancelled and waited for and TimeoutError is raised, and None waits for as
    long as it takes. A plain await of a task never drops a cancel: one that lands as the task completes is
    raised at the waiting task's next step, and asyncio.timeout counts cancellations to tell its own apart.

    The other side of that: a stop (or the limit) that lands just as the work completes wins, and its result
    is not returned, where wait_for returned it and lost the stop. When the result is something to close (an
    opened session, a connection), pass `dispose`: it gets the result that finished but will not be returned.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        async with asyncio.timeout(timeout):
            return await task
    except BaseException:
        if dispose is not None and task.done() and not task.cancelled() and task.exception() is None:
            await dispose(task.result())
        raise


async def close_connection(connection: tuple[asyncio.StreamReader, asyncio.StreamWriter]) -> None:
    """`dispose` for asyncio.open_connection: close a connection nobody will use."""
    writer = connection[1]
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
