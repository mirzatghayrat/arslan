"""0033: MemoryProposal.new_id NOT NULL -> nullable (SQLite table rebuild).

P2 Tier2 proposals (delete_suspect/preference_overwrite_suspect/append_suspect)
have no replacing new_id, but 0032 declared new_id NOT NULL. SQLite cannot
ALTER COLUMN to drop NOT NULL, so 0033 rebuilds memory_proposals via a
CREATE-new/INSERT-SELECT/DROP-old/RENAME sequence and recreates the
ix_memory_proposals_status index (the only object on the table).

- upgrade_sync is idempotent: first run rebuilds + preserves data byte-for-byte,
  second run is a no-op (the _new_id_is_nullable PRAGMA guard short-circuits).
- post-migration, a new_id=NULL row can be inserted (the old NOT NULL schema
  would reject it).
- fresh (Base.metadata.create_all) memory_proposals.new_id is already nullable
  (the models.py change) — fresh-parity; apply_pending includes "0033" as a
  no-op on fresh DBs (create_all already produced the nullable shape).
- ix_memory_proposals_status survives the rebuild.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

from server.db.migrations import runner
from server.db.migrations.versions._0032_brain_temporal import upgrade_sync as upgrade_0032
from server.db.migrations.versions._0033_memory_proposal_nullable import upgrade_sync
from server.db.models import Base

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


def _build_0032_state(path) -> None:
    """Hand-build the post-0032 (pre-0033) shape: memory_proposals exists with
    new_id NOT NULL (0032's original DDL), some real rows in it."""
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql(_OLD_USER_FACTS_DDL)
        conn.exec_driver_sql(_OLD_LEARNINGS_DDL)
        upgrade_0032(conn)
    engine.dispose()


def _row_snapshot(conn, table, cols):
    rows = conn.exec_driver_sql(
        f"SELECT {', '.join(cols)} FROM {table} ORDER BY id").fetchall()
    return [tuple(r) for r in rows]


def _table_names(conn):
    return {r[0] for r in conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _index_names(conn, table):
    return {r[1] for r in conn.exec_driver_sql(f"PRAGMA index_list({table})")}


def _new_id_notnull_flag(conn):
    for row in conn.exec_driver_sql("PRAGMA table_info(memory_proposals)"):
        if row[1] == "new_id":
            return row[3]
    raise AssertionError("new_id column not found")


# --- 1. idempotency + data preservation -----------------------------------------

def test_upgrade_sync_idempotent_and_preserves_data(tmp_path):
    db = tmp_path / "m.db"
    _build_0032_state(db)
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO memory_proposals "
            "(id, kind, table_name, new_id, old_id, reason, status, provenance, "
            "created_at, resolved_at) VALUES "
            "(1, 'supersede_suspect', 'user_facts', 5, 3, 'looks newer', 'pending', "
            "'{\"source_kind\": \"rule\"}', '2026-01-01 00:00:00', NULL)")
        conn.exec_driver_sql(
            "INSERT INTO memory_proposals "
            "(id, kind, table_name, new_id, old_id, reason, status, provenance, "
            "created_at, resolved_at) VALUES "
            "(2, 'supersede_suspect', 'learnings', 8, 4, 'contradicts', 'accepted', "
            "NULL, '2026-01-02 00:00:00', '2026-01-03 00:00:00')")

    # pre-condition: 0032 shape really is NOT NULL
    with engine.connect() as conn:
        assert _new_id_notnull_flag(conn) == 1

    with engine.begin() as conn:
        upgrade_sync(conn)  # first run: rebuild

    with engine.connect() as conn:
        assert _new_id_notnull_flag(conn) == 0   # now nullable
        before_rows = _row_snapshot(
            conn, "memory_proposals",
            ["id", "kind", "table_name", "new_id", "old_id", "reason", "status",
             "provenance", "created_at", "resolved_at"])
        before_tables = _table_names(conn)
        before_indexes = _index_names(conn, "memory_proposals")

    assert before_rows == [
        (1, "supersede_suspect", "user_facts", 5, 3, "looks newer", "pending",
         '{"source_kind": "rule"}', "2026-01-01 00:00:00", None),
        (2, "supersede_suspect", "learnings", 8, 4, "contradicts", "accepted",
         None, "2026-01-02 00:00:00", "2026-01-03 00:00:00"),
    ]
    assert "ix_memory_proposals_status" in before_indexes

    with engine.begin() as conn:
        upgrade_sync(conn)  # second run: must be a no-op (guard short-circuits)

    with engine.connect() as conn:
        after_rows = _row_snapshot(
            conn, "memory_proposals",
            ["id", "kind", "table_name", "new_id", "old_id", "reason", "status",
             "provenance", "created_at", "resolved_at"])
        after_tables = _table_names(conn)
        after_indexes = _index_names(conn, "memory_proposals")

    assert after_rows == before_rows
    assert after_tables == before_tables
    assert after_indexes == before_indexes
    engine.dispose()


# --- 2. NULL new_id insertable post-migration -----------------------------------

def test_null_new_id_insertable_after_upgrade(tmp_path):
    db = tmp_path / "m.db"
    _build_0032_state(db)
    engine = create_engine(f"sqlite:///{db}")

    with engine.begin() as conn:
        # sanity: the OLD (0032) schema rejects a NULL new_id
        try:
            conn.exec_driver_sql(
                "INSERT INTO memory_proposals "
                "(kind, table_name, new_id, old_id, reason, status) VALUES "
                "('delete_suspect', 'user_facts', NULL, 3, 'stale', 'pending')")
        except Exception:
            pass
        else:
            raise AssertionError("expected NOT NULL constraint to reject new_id=NULL pre-migration")

    with engine.begin() as conn:
        upgrade_sync(conn)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO memory_proposals "
            "(kind, table_name, new_id, old_id, reason, status) VALUES "
            "('delete_suspect', 'user_facts', NULL, 3, 'stale', 'pending')")

    with engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT new_id, table_name, old_id FROM memory_proposals "
            "WHERE kind = 'delete_suspect'").fetchone()
    assert row == (None, "user_facts", 3)
    engine.dispose()


# --- 3. fresh-parity + apply_pending chain ---------------------------------------

def test_fresh_create_all_new_id_is_nullable(tmp_path):
    fresh_db = tmp_path / "fresh.db"
    fresh_engine = create_engine(f"sqlite:///{fresh_db}")
    Base.metadata.create_all(fresh_engine)
    with fresh_engine.connect() as conn:
        assert _new_id_notnull_flag(conn) == 0   # already nullable via models.py
    fresh_engine.dispose()


async def test_apply_pending_includes_0033_as_noop_on_fresh_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chain.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        applied = await conn.run_sync(runner.apply_pending)
    assert "0033" in applied

    async with engine.begin() as conn:
        again = await conn.run_sync(runner.apply_pending)
    assert again == []

    await engine.dispose()


# --- 4. index survives rebuild ----------------------------------------------------

def test_index_survives_rebuild(tmp_path):
    db = tmp_path / "m.db"
    _build_0032_state(db)
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        assert "ix_memory_proposals_status" in _index_names(conn, "memory_proposals")

    with engine.begin() as conn:
        upgrade_sync(conn)

    with engine.connect() as conn:
        assert "ix_memory_proposals_status" in _index_names(conn, "memory_proposals")
    engine.dispose()
