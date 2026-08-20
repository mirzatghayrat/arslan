"""0041: scheduled_tasks.target — who runs a scheduled task.

P2 makes a task with no spawn run Arslan itself, which collides with an
existing meaning of the same NULL: `spawn_id` is ondelete SET NULL, so a task
whose spawn was deleted also has NULL there — and that case must keep failing
cleanly (review S8) so the 3-fail auto-pause retires it. Two different
intentions cannot share one absent value, so the intention becomes a column.

Existing rows backfill to "spawn": every task that predates this column was
created through an API that REQUIRED a spawn, so "spawn" is their history, not
a guess.
"""
from __future__ import annotations


def _tables(connection) -> set[str]:
    return {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def upgrade_sync(connection) -> None:
    if "scheduled_tasks" not in _tables(connection):
        return
    existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(scheduled_tasks)")}
    if "target" not in existing:
        connection.exec_driver_sql(
            "ALTER TABLE scheduled_tasks ADD COLUMN target VARCHAR(10) NOT NULL DEFAULT 'spawn'")


def downgrade_sync(connection) -> None:
    """Leaving the column is harmless (older code never reads it)."""
    return
