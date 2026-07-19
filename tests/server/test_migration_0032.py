"""0032: user_facts/learnings temporal columns (valid_from/superseded_by[/provenance])
+ memory_proposals table + legacy backfill.

- upgrade_sync is idempotent on a hand-built 0031-shape DB (safe to re-run).
- legacy rows backfill valid_from from created_at (NULL stays NULL); provenance
  defaults to {"source_kind": "legacy"} and reads back as a dict through the ORM
  JSON column; superseded_by stays NULL. learnings gets the same valid_from
  backfill only (no provenance column there — source_kind/source_ref already
  carry it, see the models.py comment on Learning).
- fresh (Base.metadata.create_all) and migrated-from-0031-state schemas agree
  exactly (set equality via PRAGMA table_info) on user_facts/learnings/
  memory_proposals columns — catches drift in either direction (a column added
  only to models.py, or only to the migration).
- apply_pending includes "0032" in the boot chain and a second run is a no-op.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from server.db.migrations import runner
from server.db.migrations.versions._0032_brain_temporal import upgrade_sync
from server.db.models import Base, Learning, UserFact

_OLD_USER_FACTS_DDL = (
    "CREATE TABLE user_facts (id INTEGER PRIMARY KEY, content TEXT NOT NULL, "
    "source VARCHAR(20), sensitive BOOLEAN, category VARCHAR(30), label VARCHAR(40), "
    "confidence FLOAT, created_at DATETIME)"
)
_OLD_LEARNINGS_DDL = (
    "CREATE TABLE learnings (id INTEGER PRIMARY KEY, content TEXT NOT NULL, "
    "label VARCHAR(60), source_kind VARCHAR(20) NOT NULL, source_ref JSON NOT NULL, "
    "spawn_id INTEGER, confidence FLOAT, created_at DATETIME)"
)


def _build_0031_state(path) -> None:
    """Hand-build the pre-0032 (0031-cumulative) shape of user_facts/learnings —
    no memory_proposals table, no temporal columns. Mirrors the pattern in
    test_migration_0019.py rather than Base.metadata.create_all, which already
    carries the 0032 columns once models.py is updated."""
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql(_OLD_USER_FACTS_DDL)
        conn.exec_driver_sql(_OLD_LEARNINGS_DDL)
    engine.dispose()


def _row_snapshot(conn, table, cols):
    rows = conn.exec_driver_sql(
        f"SELECT {', '.join(cols)} FROM {table} ORDER BY id").fetchall()
    return [tuple(r) for r in rows]


def _table_names(conn):
    return {r[0] for r in conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


# --- 1. idempotency -----------------------------------------------------------

def test_upgrade_sync_idempotent_on_0031_state(tmp_path):
    db = tmp_path / "m.db"
    _build_0031_state(db)
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO user_facts (id, content, created_at) "
            "VALUES (1, 'likes tea', '2026-01-01 00:00:00')")
        conn.exec_driver_sql(
            "INSERT INTO learnings (id, content, source_kind, source_ref, created_at) "
            "VALUES (1, 'retry on 429', 'distill', '{}', '2026-01-01 00:00:00')")

    with engine.begin() as conn:
        upgrade_sync(conn)  # first run must not raise

    with engine.connect() as conn:
        before_facts = _row_snapshot(
            conn, "user_facts", ["id", "valid_from", "superseded_by", "provenance"])
        before_learnings = _row_snapshot(
            conn, "learnings", ["id", "valid_from", "superseded_by"])
        before_tables = _table_names(conn)

    with engine.begin() as conn:
        upgrade_sync(conn)  # second run: must not raise, must be a no-op

    with engine.connect() as conn:
        after_facts = _row_snapshot(
            conn, "user_facts", ["id", "valid_from", "superseded_by", "provenance"])
        after_learnings = _row_snapshot(
            conn, "learnings", ["id", "valid_from", "superseded_by"])
        after_tables = _table_names(conn)

    assert after_facts == before_facts
    assert after_learnings == before_learnings
    assert after_tables == before_tables
    engine.dispose()


# --- 2. backfill ----------------------------------------------------------------

def test_backfill_valid_from_and_legacy_provenance(tmp_path):
    db = tmp_path / "m.db"
    _build_0031_state(db)
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO user_facts (id, content, created_at) "
            "VALUES (1, 'has a cat', '2026-01-01 00:00:00')")
        conn.exec_driver_sql(
            "INSERT INTO user_facts (id, content, created_at) "
            "VALUES (2, 'likes tea', NULL)")
        conn.exec_driver_sql(
            "INSERT INTO learnings (id, content, source_kind, source_ref, created_at) "
            "VALUES (1, 'retry on 429', 'distill', '{}', '2026-01-01 00:00:00')")
        conn.exec_driver_sql(
            "INSERT INTO learnings (id, content, source_kind, source_ref, created_at) "
            "VALUES (2, 'batch writes', 'distill', '{}', NULL)")

    with engine.begin() as conn:
        upgrade_sync(conn)

    with Session(engine) as session:
        f1 = session.get(UserFact, 1)
        f2 = session.get(UserFact, 2)
        l1 = session.get(Learning, 1)
        l2 = session.get(Learning, 2)

    assert f1.valid_from == datetime(2026, 1, 1, 0, 0, 0)
    assert f2.valid_from is None
    assert f1.superseded_by is None
    assert f2.superseded_by is None
    assert f1.provenance == {"source_kind": "legacy"}
    assert isinstance(f1.provenance, dict)  # reads back as a dict, not a JSON string
    assert f2.provenance == {"source_kind": "legacy"}

    assert l1.valid_from == datetime(2026, 1, 1, 0, 0, 0)
    assert l2.valid_from is None
    assert l1.superseded_by is None
    assert l2.superseded_by is None

    engine.dispose()


# --- 3. fresh-parity, both directions --------------------------------------------

def test_fresh_and_migrated_schemas_match_exactly(tmp_path):
    # Path A: fresh — Base.metadata.create_all (the ORM's own idea of the schema).
    fresh_db = tmp_path / "fresh.db"
    fresh_engine = create_engine(f"sqlite:///{fresh_db}")
    Base.metadata.create_all(fresh_engine)
    with fresh_engine.connect() as conn:
        fresh_cols = {
            table: {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for table in ("user_facts", "learnings", "memory_proposals")
        }
    fresh_engine.dispose()

    # Path B: migrated — hand-built 0031-state + upgrade_sync.
    mig_db = tmp_path / "migrated.db"
    _build_0031_state(mig_db)
    mig_engine = create_engine(f"sqlite:///{mig_db}")
    with mig_engine.begin() as conn:
        upgrade_sync(conn)
        # Fresh-parity compares against the CURRENT ORM, so path B must include every
        # LATER migration touching these tables — 0034 adds
        # memory_proposals.conversation_id. (0033 rebuilds the table in place and is
        # already shape-compatible.)
        from server.db.migrations.versions._0034_curation_layer import (
            upgrade_sync as _m0034,
        )
        _m0034(conn)
    with mig_engine.connect() as conn:
        migrated_cols = {
            table: {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for table in ("user_facts", "learnings", "memory_proposals")
        }
    mig_engine.dispose()

    assert fresh_cols == migrated_cols


# --- 4. chain --------------------------------------------------------------------

async def test_apply_pending_includes_0032_and_is_idempotent(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chain.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        applied = await conn.run_sync(runner.apply_pending)
    assert "0032" in applied

    async with engine.begin() as conn:
        again = await conn.run_sync(runner.apply_pending)
    assert again == []

    await engine.dispose()
