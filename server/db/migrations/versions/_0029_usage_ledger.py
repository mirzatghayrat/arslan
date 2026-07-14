"""0029: S3-M3 cost visibility — usage_ledger table.

One row per (scope, model, provider) bucket of LLM usage for call sites that never
produce a Run row (router / judge / memory compaction / titler / direct spawn chat)
plus Arslan's answer path. Written best-effort by server/services/usage_ledger.py.

Idempotency (this repo re-applies every migration on every boot): CREATE TABLE/INDEX
use IF NOT EXISTS, so a second run is a no-op. Fresh DBs get the final shape from
Base.metadata.create_all (the UsageLedger ORM model), so the guards simply find the
table already present.

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-11
"""
from __future__ import annotations

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

_USAGE_LEDGER_DDL = (
    "CREATE TABLE IF NOT EXISTS usage_ledger ("
    "id INTEGER PRIMARY KEY, "
    "ts DATETIME NOT NULL, "
    "scope VARCHAR(20) NOT NULL, "
    "conversation_id VARCHAR(50), "
    "run_id INTEGER, "
    "model VARCHAR(80), "
    "provider VARCHAR(40), "
    "tokens_in INTEGER, "
    "tokens_out INTEGER, "
    "tokens_total INTEGER NOT NULL DEFAULT 0, "
    "tokens_estimated BOOLEAN NOT NULL DEFAULT 0)"
)


def _upgrade(connection) -> None:  # noqa: ANN001
    connection.exec_driver_sql(_USAGE_LEDGER_DDL)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_usage_ledger_ts ON usage_ledger (ts)")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_usage_ledger_conversation_id "
        "ON usage_ledger (conversation_id)")


def _downgrade(connection) -> None:  # noqa: ANN001
    connection.exec_driver_sql("DROP TABLE IF EXISTS usage_ledger")


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)
