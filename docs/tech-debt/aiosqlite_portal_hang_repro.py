# NOT A TEST — an attempt to reproduce, kept because it FAILED to.
#
# Two hypotheses for the >120s portal-teardown hang were built here and both
# came back CLEAN, so neither is the mechanism:
#
#   1. a straggler task merely HOLDING a connection when cancel_remaining
#      fires                                                        -> CLEAN
#   2. a straggler task cancelled while INSIDE a slow database call,
#      so the cancel lands in the connection's own teardown          -> CLEAN 3/3
#
# Run it as:  .venv/bin/python docs/tech-debt/aiosqlite_portal_hang_repro.py /tmp/x.db
# It prints CLEAN or HUNG. Both attempts were made on macOS; CI is Linux and
# under load, which is the untested difference.
#
# What IS established, from the CI traceback rather than from here, is written
# up in the memory note (arslan-aiosqlite-portal-hang). Short version: the hang
# is anyio's own thread.join() in start_blocking_portal.__exit__ — the fixture's
# own finally (dispose engines, then stop) had already completed — and the line
# before it is an aiosqlite connection whose terminate() was CANCELLED by the
# portal's stop-with-cancel, through SQLAlchemy's greenlet bridge, where the
# inner close is asyncio.shield()ed and therefore outlives the cancellation.

"""Reproduce the portal-teardown hang deterministically.

The CI traceback says the hang is anyio's own `thread.join()` in
start_blocking_portal.__exit__, and the log line just before it is an aiosqlite
connection being terminated and CANCELLED by the portal's stop-with-cancel.
So: hold a connection open in a fire-and-forget task, then tear down exactly
the way the fixture does, and see whether the thread joins.
"""
import sys, threading, time
from anyio.from_thread import start_blocking_portal
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
import sqlalchemy as sa
import anyio, asyncio

DB = sys.argv[1]

def main() -> int:
    with start_blocking_portal() as p:
        engine = create_async_engine(f"sqlite+aiosqlite:///{DB}", poolclass=NullPool)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def setup():
            async with engine.begin() as c:
                await c.exec_driver_sql("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
        p.call(setup)

        # A straggler exactly like distill/ledger: created with create_task,
        # holding a live connection, still running when teardown begins.
        async def straggler():
            async with maker() as s:
                await s.execute(sa.text("SELECT 1"))
                # Be INSIDE a database call when the cancel arrives, not asleep
                # beside one: the CI traceback shows the cancellation landing in
                # the connection's own terminate path, through SQLAlchemy's
                # greenlet bridge, which is where it can fail to unwind.
                await s.execute(sa.text(
                    "WITH RECURSIVE c(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM c WHERE i<80000000)"
                    " SELECT count(*) FROM c"))

        async def spawn():
            asyncio.get_running_loop().create_task(straggler())
            await anyio.sleep(0.4)              # let it get INTO the slow call
        p.call(spawn)

        # --- the fixture's teardown, verbatim ---
        try:
            p.call(engine.dispose)
        finally:
            p.call(p.stop, True)
    return 0

t = threading.Thread(target=main, daemon=True)
t.start()
t.join(timeout=25)
print("HUNG" if t.is_alive() else "CLEAN")
