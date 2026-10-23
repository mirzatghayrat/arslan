"""K9b (0.1.63): a message sent while a turn runs reaches that turn at its next tool boundary (card K9).

One box per conversation, open only while a turn holds the conversation's turn lock (ws/arslan.py `_turn`).
A socket's reader puts a `user_message` here instead of in its own inbox when a turn runs and no card of
that window waits (a waiting card keeps its rule: typing answers it No, with the message as the note, and
the message runs next). The sender is told `queued` at once, as before.

The running turn's tool loop reads what is in the box after each tool, or each group of reads run together
(K9a). A message is only ever taken whole, once, and becomes part of the turn when the next model request
carries it (tool_loop: stored, its sender told); one the turn ends without sending goes back. What is still
here when the turn ends goes back to the inbox of the socket that sent it and runs once, as the next turn: a
turn that was already writing its answer has no boundary left. A socket that closes takes its messages back
first (`withdraw`), and waits for the ones a turn already took to be part of it or back (`settled`), all
ahead of the close. `put` refuses when no turn is open, so a message never waits in a closed box.

`steering_off` (setting, no UI) leaves every such message queued, as before K9b. DELETE-BY: v0.1.64, when
M3 #10 passes and v0.1.63 has no steering issue (card K9).
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass(eq=False)
class Steer:
    content: str
    source: str | None                                 # "phone" from the Arslan Bridge, else the window
    frame: dict                                        # the user_message as it came, to hand back
    tell: Callable[[dict], Awaitable[None]]            # the sending socket's own sender
    inbox: asyncio.Queue                               # the sending socket's inbox: where it goes back
    sink: Callable[[dict], None] | None = None         # the sending socket's fan-out sink (never echoed to)
    done: asyncio.Event = field(default_factory=asyncio.Event)     # part of the turn, or handed back

    def hand_back(self) -> None:
        self.inbox.put_nowait(self.frame)
        self.settle()

    def settle(self) -> None:
        self.done.set()
        if self in _taken:
            _taken.remove(self)


_open: dict[str, list[Steer]] = {}
_taken: list[Steer] = []           # taken by a turn, not yet part of it nor handed back


def open_box(conversation_id: str) -> None:
    _open[conversation_id] = []


def put(conversation_id: str, steer: Steer) -> bool:
    """Into the running turn's box; False when no turn is open (the message waits as before)."""
    box = _open.get(conversation_id)
    if box is None:
        return False
    box.append(steer)
    return True


def waiting(conversation_id: str) -> bool:
    return bool(_open.get(conversation_id))


def take(conversation_id: str) -> list[Steer]:
    """Everything in the box, in the order it came; the box stays open for the rest of the turn."""
    box = _open.get(conversation_id)
    if not box:
        return []
    taken, box[:] = list(box), []
    _taken.extend(taken)
    return taken


def withdraw(conversation_id: str, inbox: asyncio.Queue) -> list[Steer]:
    """A socket closed: its messages still waiting leave the box, to go into its inbox ahead of the close
    (handed back at the turn's end they would land after it, and never run)."""
    box = _open.get(conversation_id)
    if not box:
        return []
    mine = [steer for steer in box if steer.inbox is inbox]
    box[:] = [steer for steer in box if steer.inbox is not inbox]
    return mine


async def settled(inbox: asyncio.Queue) -> None:
    """A socket closed: its messages a turn already took become part of that turn (its next request) or come
    back into this inbox (the turn ended first), still ahead of the close (review of #393)."""
    for steer in [steer for steer in _taken if steer.inbox is inbox]:
        await steer.done.wait()


def close_box(conversation_id: str) -> None:
    """The turn ends: what it never took goes back to its sender's inbox, to run once as the next turn."""
    for steer in _open.pop(conversation_id, None) or []:
        steer.hand_back()


def insertable(frame: dict) -> bool:
    """Plain text only: a message with images or an attachment waits for its own turn, as before."""
    return bool(str(frame.get("content") or "").strip()) and not frame.get("images") \
        and not str(frame.get("attached_context") or "").strip()


async def enabled() -> bool:
    try:
        from server.db import session as db_session
        from server.services import settings_service
        async with db_session.AsyncSessionLocal() as db:
            return not await settings_service.steering_off(db)
    except Exception:  # noqa: BLE001 — an unreadable setting is the default: steering on
        return True
