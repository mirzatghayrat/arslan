"""K9b follow-up (⓪Plan's re-review of #393, low): a closing socket waits for the messages a turn took from it
(`steering.settled`), but only so long. Today one database write sits between taking a message and making it part
of the turn; a future await there must not stall a socket's teardown for ever. Past the bound the socket closes,
and a WARNING says how many messages it closed without.
"""
from __future__ import annotations

import asyncio
import logging

from server.services import steering


def _taken(inbox: asyncio.Queue, content: str = "use the other folder") -> steering.Steer:
    async def tell(_frame):
        return None
    steer = steering.Steer(content, None, {"type": "user_message", "content": content}, tell, inbox)
    steering._taken.append(steer)
    return steer


async def test_a_message_that_never_settles_holds_the_close_only_until_the_bound(monkeypatch, caplog):
    monkeypatch.setattr(steering, "SETTLE_WAIT_S", 0.2)
    inbox: asyncio.Queue = asyncio.Queue()
    _taken(inbox)
    try:
        with caplog.at_level(logging.WARNING, logger=steering.__name__):
            started = asyncio.get_running_loop().time()
            await asyncio.wait_for(steering.settled(inbox), 5)       # the bound, not this test's guard, ends it
            waited = asyncio.get_running_loop().time() - started
        assert 0.15 <= waited < 2
        assert any(r.levelno == logging.WARNING and "1 message" in r.getMessage() for r in caplog.records)
    finally:
        steering._taken.clear()


async def test_a_message_that_settles_in_time_is_waited_for_and_nothing_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(steering, "SETTLE_WAIT_S", 5)
    inbox: asyncio.Queue = asyncio.Queue()
    steer = _taken(inbox)
    try:
        asyncio.get_running_loop().call_later(0.05, steer.hand_back)
        with caplog.at_level(logging.WARNING, logger=steering.__name__):
            await asyncio.wait_for(steering.settled(inbox), 5)
        assert inbox.get_nowait() == steer.frame and steering._taken == []
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    finally:
        steering._taken.clear()


async def test_another_sockets_message_is_not_waited_for(monkeypatch):
    monkeypatch.setattr(steering, "SETTLE_WAIT_S", 5)
    mine, theirs = asyncio.Queue(), asyncio.Queue()
    _taken(theirs)
    try:
        await asyncio.wait_for(steering.settled(mine), 1)
    finally:
        steering._taken.clear()
