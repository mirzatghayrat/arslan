"""A task cancelled in the middle of a statement frees SQLite's write lock at once (0.1.61 PR 2c).

THE FAULT. A task's transaction INSERTs, then a SELECT in the same transaction is cancelled while
it runs (Stop on a job, a closed socket, a timeout). SQLAlchemy invalidates the connection and
closes it, but Python's `sqlite3` close is `sqlite3_close_v2`: while the cancelled SELECT's cursor
is still alive (the exception's traceback keeps it in a reference cycle) the connection stays open
as a "zombie" and keeps its transaction, and with it the write lock, until the garbage collector
finalizes that cursor. Meanwhile every other write waits the 5 s `busy_timeout` and then fails
with "database is locked" (CI 38293278888; the F1 section of PR 2's CI report).

THE FIX (`server/db/session.py`): when SQLAlchemy invalidates a connection because its task was
cancelled, the transaction is rolled back before the connection is closed. The rollback queues
behind the cancelled statement on aiosqlite's worker thread, so the lock is free as soon as that
statement ends, with no garbage collection.

The cancelled statement here is a SELECT that waits on a gate the test holds, so the cancel lands
inside it for certain, and the test decides when it ends. The garbage collector is off throughout:
the lock must not depend on it.
"""
from __future__ import annotations

import asyncio
import gc
import sqlite3
import threading
import time

import aiosqlite
import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.db.session import build_engine


class _Gate:
    """A SQL function `held()` that blocks aiosqlite's worker thread until the test opens it."""

    def __init__(self) -> None:
        self.inside = threading.Event()
        self.open = threading.Event()

    def __call__(self) -> int:
        self.inside.set()
        self.open.wait(10)
        return 1


def _lock(path) -> str:
    """'free' when a fresh connection can take SQLite's write lock right now (no waiting)."""
    con = sqlite3.connect(path, timeout=0)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.rollback()
        return "free"
    except sqlite3.OperationalError as exc:
        return f"held ({exc})"
    finally:
        con.close()


async def _lock_within(path, seconds: float) -> str:
    deadline = time.monotonic() + seconds
    state = _lock(path)
    while state != "free" and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
        state = _lock(path)
    return state


@pytest.fixture
def no_gc():
    gc.disable()
    try:
        yield
    finally:
        gc.enable()
        gc.collect()           # a failing run must not leave its zombie's lock to the next test


@pytest.fixture
async def db(tmp_path):
    path = tmp_path / "cancelled.db"
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    gate = _Gate()

    @event.listens_for(engine.sync_engine, "connect")
    def _gate_function(dbapi_conn, _record):  # noqa: ANN001
        dbapi_conn.create_function("held", 0, gate)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield path, engine, maker, gate
    finally:
        gate.open.set()
        await engine.dispose()


async def _cancel_inside_the_select(maker, gate, *, cancels: int = 1) -> asyncio.Task:
    """A transaction INSERTs, then its SELECT is cancelled while it runs. Returns the task, ended."""
    async def writer():
        async with maker() as session:
            await session.execute(text("INSERT INTO t (v) VALUES ('uncommitted')"))
            await session.execute(text("SELECT held()"))

    task = asyncio.create_task(writer())
    assert await asyncio.to_thread(gate.inside.wait, 5), "the SELECT never started"
    for _ in range(cancels):
        task.cancel()
        await asyncio.sleep(0.05)              # the cancel lands; the statement is still running
    gate.open.set()                            # the cancelled statement ends now
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    return task


async def test_a_write_cancelled_mid_select_frees_the_lock_at_once_without_gc(db, no_gc):
    path, _engine, maker, gate = db
    async with maker() as session:                       # committed before: must survive
        await session.execute(text("INSERT INTO t (v) VALUES ('committed')"))
        await session.commit()
    await _cancel_inside_the_select(maker, gate)
    assert await _lock_within(path, 0.5) == "free"
    # Another write goes through at once, and only the committed row is there.
    async with maker() as session:
        await asyncio.wait_for(session.execute(text("INSERT INTO t (v) VALUES ('after')")), 1)
        await session.commit()
        rows = (await session.execute(text("SELECT v FROM t ORDER BY id"))).scalars().all()
    assert rows == ["committed", "after"]


async def test_a_second_cancel_while_the_rollback_waits_still_frees_the_lock(db, no_gc):
    """Stop, then the socket closes: the task is cancelled again while the rollback waits behind
    the statement. The rollback is already queued on the worker thread, ahead of the close."""
    path, _engine, maker, gate = db
    await _cancel_inside_the_select(maker, gate, cancels=2)
    assert await _lock_within(path, 0.5) == "free"
    async with maker() as session:
        await asyncio.wait_for(session.execute(text("INSERT INTO t (v) VALUES ('after')")), 1)
        await session.commit()
        assert (await session.execute(text("SELECT v FROM t"))).scalars().all() == ["after"]


async def test_a_commit_already_on_its_way_is_kept_when_its_task_is_cancelled(db, no_gc, monkeypatch):
    """Committed data is never lost: the cancel lands while the COMMIT itself is on aiosqlite's
    worker thread. The rollback queues behind it, so it finds no transaction to undo."""
    path, _engine, maker, gate = db
    real_commit = aiosqlite.Connection.commit

    async def held_commit(self):
        if not gate.inside.is_set():
            def commit():
                gate()                            # the COMMIT has reached the worker; then it runs
                return self._conn.commit()
            return await self._execute(commit)
        return await real_commit(self)

    monkeypatch.setattr(aiosqlite.Connection, "commit", held_commit)

    async def writer():
        async with maker() as session:
            await session.execute(text("INSERT INTO t (v) VALUES ('committing')"))
            await session.commit()

    task = asyncio.create_task(writer())
    assert await asyncio.to_thread(gate.inside.wait, 5), "the COMMIT never started"
    task.cancel()
    await asyncio.sleep(0.05)
    gate.open.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert await _lock_within(path, 0.5) == "free"
    async with maker() as session:
        assert (await session.execute(text("SELECT v FROM t"))).scalars().all() == ["committing"]


async def test_no_connection_is_closed_twice(db, no_gc, monkeypatch):
    path, engine, maker, gate = db
    closes: dict[int, int] = {}
    real_close = aiosqlite.Connection.close

    async def counting_close(self):
        closes[id(self)] = closes.get(id(self), 0) + 1
        return await real_close(self)

    monkeypatch.setattr(aiosqlite.Connection, "close", counting_close)
    await _cancel_inside_the_select(maker, gate)
    assert await _lock_within(path, 0.5) == "free"
    async with maker() as session:
        await session.execute(text("SELECT 1"))
    await engine.dispose()
    assert closes and set(closes.values()) == {1}, closes


async def test_the_busy_timeout_stays_five_seconds(db):
    _path, engine, _maker, _gate = db
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one() == 5000
