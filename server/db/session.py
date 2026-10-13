"""Async SQLAlchemy engine, WAL pragmas, and session dependency."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.util.concurrency import in_greenlet

from server.config import settings

logger = logging.getLogger(__name__)


def build_engine(db_url: str) -> AsyncEngine:
    """Create an async engine with SQLite concurrency pragmas applied."""
    engine = create_async_engine(db_url, echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return install_cancel_rollback(engine)


def install_cancel_rollback(engine: AsyncEngine) -> AsyncEngine:
    """Give an engine the rollback below (`build_engine` does; so do the tests' own engines, so
    the app under test behaves as it does in production). Installing it twice is a no-op."""
    if not event.contains(engine.sync_engine, "invalidate", _roll_back_a_cancelled_transaction):
        event.listen(engine.sync_engine, "invalidate", _roll_back_a_cancelled_transaction)
    return engine


def _roll_back_a_cancelled_transaction(dbapi_conn, record, exception) -> None:  # noqa: ANN001
    """A task cancelled mid-statement frees SQLite's write lock at once, not when GC runs.

    On the cancel SQLAlchemy invalidates the connection and closes it, without a rollback. But
    Python's sqlite3 close is `sqlite3_close_v2`: while the cancelled statement's cursor is still
    alive (the CancelledError's traceback holds it in a reference cycle) the connection lives on
    as a zombie with its transaction open, and a transaction that has written holds the write
    lock. Every other write then waits `busy_timeout` and fails with "database is locked" until
    the garbage collector finalizes that cursor (0.1.61 PR 2c; PR 2's CI report, F1).

    So the transaction is rolled back here, before the close. The rollback queues on aiosqlite's
    worker thread behind the cancelled statement, and the close SQLAlchemy queues next comes after
    it, so the lock is free as soon as that statement ends. Nothing committed is touched: a COMMIT
    already queued runs first, and the rollback then finds no transaction. An invalidated
    connection never commits, so nothing is lost that the close would have kept.

    If the task is cancelled again while the rollback waits (Stop pressed twice, Stop then the
    socket closing, or an anyio scope, which re-delivers its cancel at every await), that
    CancelledError goes up as it is. The rollback is already queued and still frees the lock, but
    SQLAlchemy then skips the close and checks the connection back in with the cancelled statement
    alive until GC: a statement that read a table keeps its read snapshot, so the next sessions on
    that connection would read stale rows and their writes would fail at once ("database is
    locked"). So it is soft-invalidated first: recycled (closed, once) at its next checkout, never
    handed out again (PR 2c fix round 1). Outside a greenlet (the garbage collector's cleanup) no
    IO is possible, and nothing is done."""
    if not isinstance(exception, asyncio.CancelledError) or not in_greenlet():
        return
    try:
        dbapi_conn.rollback()
    except asyncio.CancelledError:
        record.invalidate(soft=True)           # cancelled again: recycle it at its next checkout
        raise
    except Exception:  # noqa: BLE001 — the close that follows still runs, as before
        logger.warning("rollback of a cancelled transaction failed", exc_info=True)


engine: AsyncEngine = build_engine(settings.db_url)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async DB session."""
    async with AsyncSessionLocal() as session:
        yield session
