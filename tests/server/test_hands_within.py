"""Hands waits through `arslan.aio.within`, not asyncio.wait_for (follow-up to #384).

On Python 3.11 wait_for returns what it awaited and drops a stop that lands just as that completes
(gh-86296). For Hands' connection that meant a stopped turn could go on holding an open socket to the
helper. With `within` the stop wins and the connection that opened in that same moment is closed.
"""
from __future__ import annotations

import asyncio
import signal

import pytest

from arslan import aio
from server.registry import hands_tools
from server.services import hands_client


class _Writer:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1

    async def wait_closed(self):
        return None

    def write(self, data):
        pass

    async def drain(self):
        return None


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)
    if pending := aio.disposing():
        await asyncio.gather(*pending)


async def test_a_stop_that_lands_as_the_connection_opens_closes_it(monkeypatch):
    gate = asyncio.Event()
    writer = _Writer()

    async def opens(*args, **kwargs):
        await gate.wait()
        return asyncio.StreamReader(), writer
    monkeypatch.setattr(asyncio, "open_unix_connection", opens)
    exchange = asyncio.create_task(hands_client._exchange({"token": "t"}, {"op": "ping"}, 5))
    await asyncio.sleep(0)
    gate.set()
    await asyncio.sleep(0)                       # the connection is open …
    exchange.cancel()                            # … and the stop lands before _exchange takes it
    with pytest.raises(asyncio.CancelledError):
        await exchange
    await _settle()
    assert writer.closed == 1


async def test_a_connection_that_does_not_open_in_time_was_never_sent(monkeypatch):
    async def never(*args, **kwargs):
        await asyncio.sleep(10)
    monkeypatch.setattr(asyncio, "open_unix_connection", never)
    monkeypatch.setattr(hands_client, "within", _shortened(0.05))
    with pytest.raises(hands_client._NotSent):
        await hands_client._exchange({"token": "t"}, {"op": "ping"}, 5)


async def test_a_reply_that_does_not_come_in_time_is_lost_and_the_connection_closed(monkeypatch):
    writer = _Writer()

    async def opens(*args, **kwargs):
        return asyncio.StreamReader(), writer         # a reader that never gets a line
    monkeypatch.setattr(asyncio, "open_unix_connection", opens)
    with pytest.raises(hands_client._Lost):
        await hands_client._exchange({"token": "t"}, {"op": "ping"}, 0.05)
    assert writer.closed == 1


def _shortened(limit):
    """`within` with every limit cut to `limit` (the connection's own 5 s is not worth waiting for here)."""
    async def short(awaitable, timeout, **kwargs):
        return await aio.within(awaitable, min(timeout, limit), **kwargs)
    return short


@pytest.fixture
def spawned(monkeypatch):
    """The processes `_run` starts, so a test can see whether each one is still running."""
    processes = []
    real = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        process = await real(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return processes


async def _killed(process) -> bool:
    async with asyncio.timeout(3):
        return await process.wait() == -signal.SIGKILL


async def test_a_mac_automation_command_past_its_limit_is_stopped_and_says_so(spawned):
    started = asyncio.get_running_loop().time()
    out = await hands_tools._run(["/bin/sleep", "30"], timeout=0.2)
    assert out == {"ok": False, "external": False, "error": "timed out"}
    assert asyncio.get_running_loop().time() - started < 3
    assert await _killed(spawned[0])


async def test_a_mac_automation_command_whose_turn_is_stopped_is_killed(spawned):
    run = asyncio.create_task(hands_tools._run(["/bin/sleep", "30"], timeout=60))
    async with asyncio.timeout(3):
        while not spawned:
            await asyncio.sleep(0.01)
    run.cancel()                                   # the turn is stopped well inside the command's limit
    with pytest.raises(asyncio.CancelledError):
        await run
    assert await _killed(spawned[0])


async def test_a_mac_automation_command_that_finishes_answers_as_before(spawned):
    out = await hands_tools._run(["/bin/echo", "done"], timeout=5)
    assert out["ok"] is True and out["text"].strip() == "done"
    assert spawned[0].returncode == 0
