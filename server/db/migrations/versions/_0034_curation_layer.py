"""0034: 整理层 (curation layer) — two columns the background sweep needs.

``distilled_sessions.reason``
    NULL for a normal idempotency marker (the pre-existing meaning: this
    (conversation, spawn) pair was distilled). ``'curation_gave_up'`` marks a pair the
    background sweep permanently abandoned after repeated failures. Writing a real row
    is what makes the give-up TERMINAL: the sweep's candidate query is an anti-join
    against this table, so an abandoned pair leaves the candidate set instead of being
    re-selected (and re-charged to the LLM) on every tick, and the decision survives a
    process restart — an in-process counter alone would reset on every boot.

    🔴 The give-up marker must NOT poison the interactive path: `_distill_one`'s
    idempotency check treats a `curation_gave_up` row as NOT-distilled for interactive
    callers, and a successful interactive distill upserts the row back to reason=NULL.
    Only the sweep treats it as terminal.

``memory_proposals.conversation_id``
    Which conversation produced a curation proposal. Needed as a real, indexable column
    for the sweep's propose-time dedup key (kind, table_name, old_id, conversation_id):
    two different conversations touching the SAME spawn must produce two proposals, not
    silently collapse into one. A JSON-path predicate over the existing `provenance`
    blob was rejected — this repo has zero precedent for JSON-path SQL, the column is
    unindexed, and the natural SQLAlchemy spelling compiles to
    ``JSON_QUOTE(JSON_EXTRACT(...)) = :bind`` which never matches (the quoting differs),
    i.e. the dedup would silently match nothing.

Idempotency (this repo re-applies every migration on every boot): the ALTERs are
guarded by PRAGMA table_info and the index uses IF NOT EXISTS, so a second run is a
no-op. Fresh DBs get the final shape from Base.metadata.create_all (the
DistilledSession / MemoryProposal ORM models), so the guards find everything present.
"""
from __future__ import annotations

_DISTILLED_SESSIONS_COLUMNS = (
    ("reason", "VARCHAR(30)"),
)

_MEMORY_PROPOSALS_COLUMNS = (
    ("conversation_id", "VARCHAR(50)"),
)


def _add_missing(connection, table: str, columns) -> None:
    existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
    for name, ddl in columns:
        if name not in existing:
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _upgrade(connection) -> None:
    _add_missing(connection, "distilled_sessions", _DISTILLED_SESSIONS_COLUMNS)
    _add_missing(connection, "memory_proposals", _MEMORY_PROPOSALS_COLUMNS)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_memory_proposals_conversation_id "
        "ON memory_proposals (conversation_id)")
    # No backfill: NULL is the correct legacy value for BOTH columns — an existing
    # marker IS a normal distillation, and an existing proposal predates curation.


def _downgrade(connection) -> None:
    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_memory_proposals_conversation_id")
    for table, cols in (("distilled_sessions", _DISTILLED_SESSIONS_COLUMNS),
                        ("memory_proposals", _MEMORY_PROPOSALS_COLUMNS)):
        for name, _ddl in cols:
            try:  # SQLite pre-3.35 cannot DROP COLUMN; best-effort for newer versions
                connection.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {name}")
            except Exception:  # noqa: BLE001 — downgrade is best-effort on old SQLite
                pass


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    _downgrade(connection)
