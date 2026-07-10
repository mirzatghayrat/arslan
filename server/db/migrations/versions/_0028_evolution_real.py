"""0028: S2 Evolution-Real schema.

- runs: add kind ('live'|'replay'), epoch (0=pre-baseline, live runs=1), continuation, final_output.
- new tables: synthetic_tasks (versioned cold-start corpus), evolution_attempts (per-attempt record).
- evolution_proposals: add base_prompt_sha (sha256 of the base prompt the gate ran against).

Idempotency (this repo re-applies every migration on every boot): each ADD COLUMN is guarded by
a PRAGMA table_info check and every CREATE TABLE/INDEX uses IF NOT EXISTS, so a second run is a
no-op. Fresh DBs get the final shape from Base.metadata.create_all (the columns/tables are on the
ORM models), so the guards simply find everything already present.

Ruling (spec §2.1): existing runs are pre-baseline epoch=0 — the DEFAULT 0 backfills them; kind
DEFAULT 'live' is fine because kind distinguishes replay, epoch is what quarantines the old corpus.

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-10
"""
from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_RUN_COLUMNS = [
    ("kind", "VARCHAR(10) NOT NULL DEFAULT 'live'"),
    ("epoch", "INTEGER NOT NULL DEFAULT 0"),
    ("continuation", "BOOLEAN NOT NULL DEFAULT 0"),
    ("final_output", "TEXT"),
]

_SYNTHETIC_TASKS_DDL = (
    "CREATE TABLE IF NOT EXISTS synthetic_tasks ("
    "id INTEGER PRIMARY KEY, "
    "spawn_id INTEGER NOT NULL REFERENCES spawns(id) ON DELETE CASCADE, "
    "version INTEGER NOT NULL DEFAULT 1, "
    "task TEXT NOT NULL, "
    "source VARCHAR(20) NOT NULL, "
    "source_run_id INTEGER, "
    "split_side VARCHAR(10) NOT NULL, "
    "status VARCHAR(10) NOT NULL DEFAULT 'active', "
    "created_at DATETIME)"
)

_EVOLUTION_ATTEMPTS_DDL = (
    "CREATE TABLE IF NOT EXISTS evolution_attempts ("
    "id INTEGER PRIMARY KEY, "
    "spawn_id INTEGER NOT NULL REFERENCES spawns(id) ON DELETE CASCADE, "
    "started_at DATETIME, "
    "finished_at DATETIME, "
    "outcome VARCHAR(20), "
    "estimate JSON, "
    "actual JSON, "
    "proposal_id INTEGER, "
    "reason TEXT NOT NULL DEFAULT '')"
)


def _upgrade(connection) -> None:  # noqa: ANN001
    tables = {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}

    if "runs" in tables:
        existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)")}
        for name, ddl in _RUN_COLUMNS:
            if name not in existing:
                connection.exec_driver_sql(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")

    connection.exec_driver_sql(_SYNTHETIC_TASKS_DDL)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_synthetic_tasks_spawn_id ON synthetic_tasks (spawn_id)")

    connection.exec_driver_sql(_EVOLUTION_ATTEMPTS_DDL)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_evolution_attempts_spawn_id ON evolution_attempts (spawn_id)")

    if "evolution_proposals" in tables:
        evo_cols = {row[1] for row in connection.exec_driver_sql(
            "PRAGMA table_info(evolution_proposals)")}
        if "base_prompt_sha" not in evo_cols:
            connection.exec_driver_sql(
                "ALTER TABLE evolution_proposals ADD COLUMN base_prompt_sha VARCHAR(64)")


def _downgrade(connection) -> None:  # noqa: ANN001
    connection.exec_driver_sql("DROP TABLE IF EXISTS evolution_attempts")
    connection.exec_driver_sql("DROP TABLE IF EXISTS synthetic_tasks")
    # SQLite pre-3.35 cannot DROP COLUMN; best-effort for newer versions.
    for name, _ in _RUN_COLUMNS:
        try:
            connection.exec_driver_sql(f"ALTER TABLE runs DROP COLUMN {name}")
        except Exception:  # noqa: BLE001 — downgrade is best-effort on old SQLite
            pass
    try:
        connection.exec_driver_sql("ALTER TABLE evolution_proposals DROP COLUMN base_prompt_sha")
    except Exception:  # noqa: BLE001 — downgrade is best-effort on old SQLite
        pass


def upgrade() -> None:
    _upgrade(op.get_bind())


def downgrade() -> None:
    _downgrade(op.get_bind())


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)
