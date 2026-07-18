"""0033: MemoryProposal.new_id NOT NULL -> nullable (SQLite table rebuild).
P2 Tier2 delete_suspect/preference_overwrite proposals have no replacing new_id.
SQLite cannot ALTER COLUMN to drop NOT NULL, so rebuild the table. Idempotent:
skip the rebuild when new_id is already nullable (PRAGMA notnull==0)."""
from __future__ import annotations

_NEW_DDL = """
CREATE TABLE memory_proposals_new (
    id INTEGER PRIMARY KEY,
    kind VARCHAR(30) NOT NULL DEFAULT 'supersede_suspect',
    table_name VARCHAR(20) NOT NULL,
    new_id INTEGER,
    old_id INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    provenance JSON,
    created_at DATETIME,
    resolved_at DATETIME
)
"""


def _new_id_is_nullable(connection) -> bool:
    for row in connection.exec_driver_sql("PRAGMA table_info(memory_proposals)"):
        if row[1] == "new_id":
            return row[3] == 0   # notnull flag == 0 ⇒ nullable
    return True   # table absent (fresh) → create_all already made it nullable


def _upgrade(connection) -> None:
    # memory_proposals must exist (0032 created it). If a fresh DB already has the
    # nullable shape from create_all, or a prior 0033 run already rebuilt it, skip.
    tables = {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "memory_proposals" not in tables or _new_id_is_nullable(connection):
        return
    connection.exec_driver_sql(_NEW_DDL)
    connection.exec_driver_sql(
        "INSERT INTO memory_proposals_new "
        "(id, kind, table_name, new_id, old_id, reason, status, provenance, created_at, resolved_at) "
        "SELECT id, kind, table_name, new_id, old_id, "
        "reason, status, provenance, created_at, resolved_at FROM memory_proposals")
    connection.exec_driver_sql("DROP TABLE memory_proposals")
    connection.exec_driver_sql("ALTER TABLE memory_proposals_new RENAME TO memory_proposals")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_memory_proposals_status ON memory_proposals (status)")


def _downgrade(connection) -> None:
    pass  # best-effort no-op: re-adding NOT NULL needs a reverse rebuild; not required


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    _downgrade(connection)
