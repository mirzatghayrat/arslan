"""0032: brain-P1 temporal semantics — user_facts/learnings valid_from/superseded_by
(+ user_facts.provenance) + memory_proposals table + legacy backfill.

user_facts gains valid_from (effective-since timestamp; NULL = "always valid", a
pure audit field that does not participate in filtering), superseded_by (a
by-convention reference to the replacing row's user_facts.id — no FK, mirrors the
rest of this schema's audit-log columns), and provenance (JSON: source_kind /
spawn_id / conversation_id / via / ...; the write path enforces it, the column
stays nullable to allow legacy backfill). learnings gains valid_from/superseded_by
only — it already carries provenance via source_kind + source_ref (see the
models.py comment on Learning; a separate provenance column there would be a
second, competing source of truth).

memory_proposals is new: a "soft flag" table for supersede/contradiction pairs the
rule layer is unsure about — write both rows, propose a pending resolution, let a
human (later: a curation-layer UI) accept or dismiss it.

Idempotency (this repo re-applies every migration on every boot): CREATE TABLE/INDEX
use IF NOT EXISTS and the ALTERs are guarded by PRAGMA table_info, so a second run
is a no-op. The backfill UPDATEs are additionally guarded by `WHERE ... IS NULL`,
so they also converge to a no-op once applied. Fresh DBs get the final shape from
Base.metadata.create_all (the UserFact/Learning/MemoryProposal ORM models), so the
guards simply find everything already present.
"""
from __future__ import annotations

_PROPOSALS_DDL = """
CREATE TABLE IF NOT EXISTS memory_proposals (
    id INTEGER PRIMARY KEY,
    kind VARCHAR(30) NOT NULL DEFAULT 'supersede_suspect',
    table_name VARCHAR(20) NOT NULL,
    new_id INTEGER NOT NULL,
    old_id INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    provenance JSON,
    created_at DATETIME,
    resolved_at DATETIME
)
"""

_USER_FACTS_COLUMNS = [("valid_from", "DATETIME"), ("superseded_by", "INTEGER"), ("provenance", "JSON")]
_LEARNINGS_COLUMNS = [("valid_from", "DATETIME"), ("superseded_by", "INTEGER")]


def _add_missing(connection, table: str, columns) -> None:
    existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
    for name, ddl in columns:
        if name not in existing:
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _upgrade(connection) -> None:
    connection.exec_driver_sql(_PROPOSALS_DDL)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_memory_proposals_status ON memory_proposals (status)")
    _add_missing(connection, "user_facts", _USER_FACTS_COLUMNS)
    _add_missing(connection, "learnings", _LEARNINGS_COLUMNS)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_user_facts_superseded_by ON user_facts (superseded_by)")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_learnings_superseded_by ON learnings (superseded_by)")
    # Backfill (idempotent: WHERE IS NULL): legacy facts get valid_from=created_at,
    # provenance=legacy; superseded_by stays NULL (legacy data has no replace history).
    connection.exec_driver_sql(
        "UPDATE user_facts SET valid_from = created_at WHERE valid_from IS NULL")
    connection.exec_driver_sql(
        "UPDATE user_facts SET provenance = '{\"source_kind\": \"legacy\"}' WHERE provenance IS NULL")
    connection.exec_driver_sql(
        "UPDATE learnings SET valid_from = created_at WHERE valid_from IS NULL")


def _downgrade(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS memory_proposals")
    for table, cols in (("user_facts", _USER_FACTS_COLUMNS), ("learnings", _LEARNINGS_COLUMNS)):
        for name, _ddl in cols:
            try:  # SQLite pre-3.35 cannot DROP COLUMN; best-effort for newer versions
                connection.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {name}")
            except Exception:  # noqa: BLE001 — downgrade is best-effort on old SQLite
                pass


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    _downgrade(connection)
