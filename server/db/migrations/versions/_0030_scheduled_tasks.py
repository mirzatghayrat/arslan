"""0030: S3-M4 scheduled tasks — scheduled_tasks + scheduled_task_runs tables.

scheduled_tasks holds the user-defined task (what to run, for whom, on what cadence)
with data-driven scheduler state (next_due_at persisted — restart-safe, missed fires
are NOT replayed). scheduled_task_runs is one row per firing (shaped after
evolution_attempts): in-flight rows have outcome NULL; finalized rows carry
'ok' | 'error' | 'skipped_overlap'.

Idempotency (this repo re-applies every migration on every boot): CREATE TABLE/INDEX
use IF NOT EXISTS, so a second run is a no-op. Fresh DBs get the final shape from
Base.metadata.create_all (the ScheduledTask/ScheduledTaskRun ORM models), so the
guards simply find the tables already present.

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-12
"""
from __future__ import annotations

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

_SCHEDULED_TASKS_DDL = (
    "CREATE TABLE IF NOT EXISTS scheduled_tasks ("
    "id INTEGER PRIMARY KEY, "
    "name VARCHAR(80) NOT NULL, "
    "prompt TEXT NOT NULL, "
    "spawn_id INTEGER REFERENCES spawns(id) ON DELETE SET NULL, "
    "conversation_id VARCHAR(50), "
    "schedule_kind VARCHAR(10) NOT NULL, "
    "interval_s INTEGER, "
    "cron VARCHAR(40), "
    "enabled BOOLEAN NOT NULL DEFAULT 1, "
    "last_fired_at DATETIME, "
    "next_due_at DATETIME, "
    "consecutive_failures INTEGER NOT NULL DEFAULT 0, "
    "paused_reason TEXT, "
    "created_at DATETIME)"
)

_SCHEDULED_TASK_RUNS_DDL = (
    "CREATE TABLE IF NOT EXISTS scheduled_task_runs ("
    "id INTEGER PRIMARY KEY, "
    "task_id INTEGER NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE, "
    "started_at DATETIME, "
    "finished_at DATETIME, "
    "outcome VARCHAR(20), "
    "run_id INTEGER, "
    "reason TEXT)"
)


def _upgrade(connection) -> None:  # noqa: ANN001
    connection.exec_driver_sql(_SCHEDULED_TASKS_DDL)
    connection.exec_driver_sql(_SCHEDULED_TASK_RUNS_DDL)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_next_due_at "
        "ON scheduled_tasks (next_due_at)")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_task_runs_task_id "
        "ON scheduled_task_runs (task_id)")


def _downgrade(connection) -> None:  # noqa: ANN001
    connection.exec_driver_sql("DROP TABLE IF EXISTS scheduled_task_runs")
    connection.exec_driver_sql("DROP TABLE IF EXISTS scheduled_tasks")


def upgrade() -> None:
    _upgrade(op.get_bind())


def downgrade() -> None:
    _downgrade(op.get_bind())


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)
