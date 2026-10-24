"""The shared test engines run SQLite as the app does (WAL, busy_timeout), and why that matters.

They used to be bare create_async_engine calls: SQLite's rollback journal with the driver's 5 s
busy timeout. A socket test's teardown cancels its turn; when that cancel lands between a
SELECT's execute and its fetch, the cursor keeps a read lock until the garbage collector
finalizes it, and the cancel record's COMMIT waits out the 5 s, past the portal's 3 s grace.
CI reported it as "N task(s) still alive 3.0s after cancel". Under WAL a reader does not block
a writer, so the COMMIT goes through.
"""
import asyncio
import gc

import aiosqlite
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.db import session as db_session
from tests.server.conftest import build_ws_client

PRODUCTION = {"journal_mode": "wal", "busy_timeout": 5000}


async def _pragmas(session) -> dict:
    values = {name: (await session.execute(text(f"PRAGMA {name}"))).scalar()
              for name in ("journal_mode", "busy_timeout", "foreign_keys")}
    values["journal_mode"] = values["journal_mode"].lower()
    return values


def _expected() -> dict:
    # foreign_keys stays off in the shared engines for now (build_engine's DELETE-BY).
    return {**PRODUCTION, "foreign_keys": 0}


async def test_the_app_client_engine_runs_as_production(client):
    async with db_session.AsyncSessionLocal() as session:
        assert await _pragmas(session) == _expected()


async def test_the_wdb_engine_runs_as_production(wdb):
    async with wdb() as session:
        assert await _pragmas(session) == _expected()


def test_the_socket_test_engine_runs_as_production(portal, tmp_path, monkeypatch):
    build_ws_client(portal, tmp_path, monkeypatch, db_name="engines.db")
    engine = portal._test_engines[-1]

    async def read():
        async with async_sessionmaker(engine, class_=AsyncSession)() as session:
            return await _pragmas(session)
    assert portal.call(read) == _expected()


async def test_a_select_cancelled_before_its_fetch_does_not_hold_up_the_next_commit(tmp_path, monkeypatch):
    # The default pool, as client and wdb use: there it is WAL that lets the COMMIT through.
    # (With NullPool, build_engine's busy_timeout pragma alone was enough in measurement, so a
    # NullPool engine here would not notice WAL going missing; the socket engine's WAL is pinned
    # by test_the_socket_test_engine_runs_as_production instead.)
    engine = db_session.build_engine(f"sqlite+aiosqlite:///{tmp_path / 'held.db'}", foreign_keys=False)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        await session.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
        await session.execute(text("INSERT INTO t (v) VALUES ('a'), ('b')"))
        await session.commit()

    parked, never, armed, unfinalized = asyncio.Event(), asyncio.Event(), [True], []
    fetchall = aiosqlite.Cursor.fetchall

    async def park_once(cursor):
        if armed:
            armed.clear()
            unfinalized.append(cursor)         # as before a GC pass: its statement stays open
            parked.set()
            await never.wait()                 # the cancel lands here: executed, never fetched
        return await fetchall(cursor)
    monkeypatch.setattr(aiosqlite.Cursor, "fetchall", park_once)

    async def reader():
        async with maker() as session:
            await session.execute(text("SELECT * FROM t"))

    try:
        task = asyncio.create_task(reader())
        await asyncio.wait_for(parked.wait(), 5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        async with maker() as session:         # the cancel record's write; on the rollback journal
            await session.execute(text("INSERT INTO t (v) VALUES ('w')"))   # this COMMIT failed:
            await session.commit()             # "database is locked", after the 5 s busy timeout
        async with maker() as session:
            assert (await session.execute(text("SELECT count(*) FROM t"))).scalar() == 3
    finally:
        unfinalized.clear()
        gc.collect()
        await engine.dispose()
