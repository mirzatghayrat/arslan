"""Unified cross-cutting usage for the Second Brain (material/learning/profile).
record() is best-effort — usage is an observation signal and must never break
retrieval. usage_map() bulk-reads for the tree/detail endpoints.

D5 adds a second, per-USE table alongside the counter (see BrainUsageEvent). The
counter answers "how many times / most recently"; the event log answers "when", which
is what the frontend's activity timeline needs. The event log is BOUNDED by
prune_events() — an append-only table with no ceiling would be unbounded growth under
a new name, which is precisely what the counter design avoided.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text as sa_text

from server.db import session as db_session

logger = logging.getLogger(__name__)

#: Kinds that actually produce events. record() has exactly three call sites, all in
#: knowledge.py's retrieval injection. There is NO record("profile", ...) anywhere in
#: the repo, so profile facts contribute nothing to the timeline. The read endpoint
#: reports this rather than letting the UI imply four-kind coverage.
COVERED_KINDS = ("material", "learning", "note")

#: Rows deleted per transaction by the pruner. Bounded so a large backlog cannot hold a
#: write lock long enough to stall the app under WAL; the pruner LOOPS until clean, so
#: this bounds latency per batch, never total work.
PRUNE_BATCH_ROWS = 10_000

#: Hard ceiling on one read-endpoint page. An unbounded limit over an append-only table
#: is a self-inflicted DoS.
MAX_EVENT_PAGE = 2_000
DEFAULT_EVENT_PAGE = 500

#: Default window when the caller does not pass `since`.
DEFAULT_EVENT_WINDOW_DAYS = 7


async def record(kind: str, ref_key: str, *, used_ref: str | None) -> None:
    """Increment usage for one entity (upsert on the (kind, ref_key) unique index) and
    append one event row.

    Fail-open: any error is swallowed — usage is never allowed to break retrieval.

    The two writes share ONE session but commit SEPARATELY, which is deliberate in both
    halves. Sharing the session keeps this hot path (called once per injected item) to
    a single connection. Committing separately keeps the failures independent: the
    counter is the older and more important signal — it drives node size and the entry
    panel — and the newer event table is exactly the thing a migration-lagging DB can
    be missing, so it must not be able to take the counter down with it. The counter is
    already durably committed before the event insert is attempted.
    """
    ts = datetime.utcnow()
    try:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(sa_text(
                "INSERT INTO brain_usage (kind, ref_key, usage_count, last_used_at, last_used_ref, created_at) "
                "VALUES (:k, :r, 1, :ts, :ur, :ts) "
                "ON CONFLICT(kind, ref_key) DO UPDATE SET "
                "usage_count = usage_count + 1, last_used_at = :ts, last_used_ref = :ur"),
                {"k": kind, "r": ref_key, "ts": ts, "ur": used_ref})
            await db.commit()

            try:
                await db.execute(sa_text(
                    "INSERT INTO brain_usage_events (kind, ref_key, used_at, used_ref) "
                    "VALUES (:k, :r, :ts, :ur)"),
                    {"k": kind, "r": ref_key, "ts": ts, "ur": used_ref})
                await db.commit()
            except Exception as exc:  # noqa: BLE001 — timeline never worth a failed read
                logger.warning("brain_usage event append failed (non-fatal): %s", exc)
    except Exception as exc:  # noqa: BLE001 — usage never fatal
        logger.warning("brain_usage.record failed (non-fatal): %s", exc)


async def usage_map(keys: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """Return {(kind, ref_key): {usage_count, last_used_at, last_used_ref}} for the
    subset that has rows. Missing keys are simply absent. Fail-open → {}."""
    if not keys:
        return {}
    try:
        async with db_session.AsyncSessionLocal() as db:
            rows = (await db.execute(sa_text(
                "SELECT kind, ref_key, usage_count, last_used_at, last_used_ref FROM brain_usage"))).all()
        wanted = set(keys)
        out: dict[tuple[str, str], dict] = {}
        for k, r, n, ts, ur in rows:
            if (k, r) in wanted:
                out[(k, r)] = {"usage_count": n, "last_used_at": ts, "last_used_ref": ur}
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("brain_usage.usage_map failed (non-fatal): %s", exc)
        return {}


# ---------------------------------------------------------------------------------
# Retention. 🔴 This is not housekeeping bolted on afterwards — it is the condition
# under which the event table was approved at all. Two gates, because either alone
# leaks: age cannot bound a burst (a chatty week blows any budget while every event is
# well inside the window), and a row cap alone keeps ancient rows alive on a quiet
# install forever.
# ---------------------------------------------------------------------------------


async def _delete_batch(where_sql: str, params: dict) -> int:
    """Delete at most PRUNE_BATCH_ROWS rows matching `where_sql`, in ONE transaction.

    SQLite has no DELETE ... LIMIT without the optional compile flag, so the bound is
    expressed as a subselect over the primary key — portable and index-friendly.
    """
    async with db_session.AsyncSessionLocal() as db:
        result = await db.execute(sa_text(
            "DELETE FROM brain_usage_events WHERE id IN ("
            f"  SELECT id FROM brain_usage_events WHERE {where_sql} "
            "  ORDER BY used_at ASC LIMIT :batch)"),
            {**params, "batch": PRUNE_BATCH_ROWS})
        await db.commit()
        return result.rowcount or 0


async def prune_events(*, retention_days: int, max_rows: int) -> int:
    """Enforce both retention gates. Returns the number of rows deleted.

    Batched and looping: a single bounded DELETE would leave a backlog that never
    shrinks, which is the no-ceiling failure in disguise. Each batch is its own
    transaction, so a huge first prune never holds one long write lock.

    `retention_days <= 0` DISABLES the age gate (matching run_debug_retention_days) —
    reading 0 as "delete everything older than now" would erase the whole log on a
    typo. `max_rows <= 0` likewise disables the count gate.

    Fail-open: retention is maintenance; it must never propagate into the caller's
    heartbeat loop.
    """
    deleted = 0
    try:
        if retention_days > 0:
            cutoff = datetime.utcnow() - timedelta(days=retention_days)
            while True:
                n = await _delete_batch("used_at < :cutoff", {"cutoff": cutoff})
                deleted += n
                if n < PRUNE_BATCH_ROWS:
                    break

        if max_rows > 0:
            while True:
                async with db_session.AsyncSessionLocal() as db:
                    total = (await db.execute(sa_text(
                        "SELECT COUNT(*) FROM brain_usage_events"))).scalar() or 0
                excess = total - max_rows
                if excess <= 0:
                    break
                # keep the NEWEST max_rows: delete the oldest `excess`, batch-bounded.
                async with db_session.AsyncSessionLocal() as db:
                    result = await db.execute(sa_text(
                        "DELETE FROM brain_usage_events WHERE id IN ("
                        "  SELECT id FROM brain_usage_events "
                        "  ORDER BY used_at ASC LIMIT :n)"),
                        {"n": min(excess, PRUNE_BATCH_ROWS)})
                    await db.commit()
                    n = result.rowcount or 0
                deleted += n
                if n == 0:      # nothing deletable — do not spin
                    break
    except Exception as exc:  # noqa: BLE001 — maintenance is never fatal
        logger.warning("brain_usage.prune_events failed (non-fatal): %s", exc)
    return deleted
