"""K9a (0.1.63): consecutive read-only calls of one reply run at the same time (card K9).

A run is two or more calls in a row, each one of READS or an MCP tool whose server says it only reads
(and on a server not already in the run), called by its own name (not through use_tool) with arguments
that parse and fit its table. Any other call ends the run and goes alone, in its place, as before.

Each call of a run still goes through `_dispatch_tool` with every gate, one after another in the reply's
order: a refused fetch budget or the turn's tool limit lands on the same call as before. Only the executors
overlap, at most CONCURRENCY at once. A call's record (its `tool_call` and `tool_result` frames, its history
record, its trace entries) is held and handed over in the reply's order, the two frames together: every
consumer that pairs them by position (RunRecorder's steps, the phone's reads, the window's store) sees
today's call, result, call, result. The run's lines arrive when it ends.

The whole run finishes before the loop records its first call, so nothing of it outlives the batch;
stopping the turn while it runs stops every call of it.

`tools_serial` (setting, no UI) runs everything one at a time again. DELETE-BY: v0.1.64, when v0.1.63's
M1 shows parallel no worse than serial twice running and the pairing tests stay green (card K9 §9).
"""
from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from server.orchestrator import run_trace

#: Reads that never show a card and share no state with each other (⓪Plan's Q2). Not render_chart,
#: delegate_work, update_plan, browser_* or desktop_* (one browser, one desktop).
READS = frozenset({"web_search", "web_extract", "read_skill", "recall", "read_file", "list_dir", "search_files",
                   "list_my_tasks", "list_nodes", "list_my_capabilities", "whats_new", "task_progress",
                   "background_status", "mac_list_shortcuts"})
CONCURRENCY = 4

_SLOT: contextvars.ContextVar[_Slot | None] = contextvars.ContextVar("parallel_read_slot", default=None)


@dataclass
class _Slot:
    name: str
    args: dict
    places: asyncio.Semaphore
    admitted: asyncio.Event = field(default_factory=asyncio.Event)
    frames: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    convo: list[dict] = field(default_factory=list)
    run_trace: list[dict] = field(default_factory=list)
    task: asyncio.Task | None = None

    def emit(self, frame: dict) -> None:
        """Held, the tool_call frame too: it goes out next to its result (review B1 on #368)."""
        self.frames.append(frame)


@asynccontextmanager
async def executing():
    """Around the executor in `_dispatch_tool`: the call passed every gate. In a run, the next call's
    gates may start now, and this one waits for a place. Outside a run, nothing."""
    slot = _SLOT.get()
    if slot is None:
        yield
        return
    slot.admitted.set()
    async with slot.places:
        yield


def _server(key: str) -> int | None:
    if not key.startswith("mcp_") or "__" not in key:
        return None
    try:
        return int(key.split("__", 1)[0].removeprefix("mcp_"))
    except ValueError:
        return None


async def _mcp_reads(keys: set[str]) -> set[str]:
    """The MCP tools among `keys` whose server says they only read (S1's read_only: readOnlyHint, and
    not destructiveHint). Unreadable means none."""
    if not keys:
        return set()
    try:
        from sqlalchemy import select

        from server.db import session as db_session
        from server.db.models import Tool
        from server.mcp.discovery import read_only
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(select(Tool.key, Tool.annotations).where(Tool.key.in_(keys)))).all()
        return {key for key, hints in rows if read_only(hints)}
    except Exception:  # noqa: BLE001 — not knowing is not a read
        return set()


async def _serial() -> bool:
    try:
        from server.db import session as db_session
        from server.services import settings_service
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.tools_serial(db)
    except Exception:  # noqa: BLE001 — an unreadable setting is the default: together
        return False


class Batch:
    """One reply's calls: which consecutive ones run together, and their held records."""

    def __init__(self, calls: list[tuple[str, dict] | None], reads: set[str]):
        self.calls = calls
        self.reads = reads
        self.slots: dict[int, _Slot] = {}
        self.tried: set[int] = set()

    def _run_from(self, start: int) -> list[int]:
        members: list[int] = []
        servers: set[int] = set()
        for index in range(start, len(self.calls)):
            call = self.calls[index]
            if call is None or call[0] not in self.reads:
                break
            server = _server(call[0])
            if server is not None:
                if server in servers:
                    break
                servers.add(server)
            members.append(index)
        return members

    def launchable(self, index: int) -> bool:
        return index not in self.tried and len(self._run_from(index)) >= 2

    def has(self, index: int) -> bool:
        return index in self.slots

    async def run(self, start: int, dispatch: Callable[..., Awaitable[dict]], *,
                  exhausted: Callable[[], bool]) -> None:
        """Start the run at `start`: each call's gates after the previous one's, the executors together.
        Returns when every started call has finished. A call the turn's tool limit refuses, and every
        one after it, is not started: the loop handles it alone, as before."""
        members = self._run_from(start)
        self.tried.update(members)
        places = asyncio.Semaphore(CONCURRENCY)
        started: list[asyncio.Task] = []
        try:
            for index in members:
                if exhausted():
                    break
                name, args = self.calls[index]
                slot = self.slots[index] = _Slot(name, args, places)
                slot.task = asyncio.create_task(self._one(slot, dispatch))
                started.append(slot.task)
                passed = asyncio.create_task(slot.admitted.wait())
                try:
                    await asyncio.wait({slot.task, passed}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    passed.cancel()             # a stop here leaves no waiter behind
                if slot.task.done() and (slot.task.cancelled() or slot.task.exception() is not None):
                    break                       # e.g. BudgetExceeded: it is raised when the loop takes it
            await asyncio.wait(started)
        except BaseException:
            for task in started:
                task.cancel()
            if started:
                await asyncio.wait(started)
            raise

    @staticmethod
    async def _one(slot: _Slot, dispatch) -> dict:
        _SLOT.set(slot)
        with run_trace.collecting() as held:
            slot.run_trace = held
            return await dispatch(slot.name, slot.args, emit=slot.emit, tool_trace=slot.trace, convo=slot.convo)

    def take(self, index: int, *, emit: Callable[[dict], None], tool_trace: list, convo: list) -> dict:
        """The call's held record, in its place: frames, trace, history. Raises what the call raised."""
        slot = self.slots.pop(index)
        for frame in slot.frames:
            emit(frame)
        tool_trace.extend(slot.trace)
        convo.extend(slot.convo)
        run_trace.extend(slot.run_trace)
        return slot.task.result()


async def plan(calls: list[tuple[str, dict] | None]) -> Batch | None:
    """The reply's calls (name and arguments, or None for one that cannot be a read: it does not parse,
    does not fit its table, or is not called by its own name). None when nothing can run together."""
    keys = {call[0] for call in calls if call is not None}
    candidates = {key for key in keys if key in READS or _server(key) is not None}
    if sum(call is not None and call[0] in candidates for call in calls) < 2:
        return None
    reads = (candidates & READS) | await _mcp_reads({key for key in candidates if _server(key) is not None})
    batch = Batch(calls, reads)
    if not any(batch.launchable(index) for index in range(len(calls))) or await _serial():
        return None
    return batch
