"""0100 (v0.1.64 SUB7): drop `task_workers`, the deleted helpers' table.

SUB6 deleted `delegate_work`, the helpers and the table's model; nothing has read or written `task_workers`
since. The drop is its own step, after the code (v0.1.64 plan §6: code can be reverted, a table can't). Its rows
(past helper runs: brief, status, result) are in the upgrade backup the runner takes before any pending migration
(`prepare_upgrade_backup`) until that backup is pruned; only the newest three are kept (`upgrade_backup.py`).
No table points at it; its own foreign keys (companion_tasks, task_attempts, runs) go with it and delete
nothing else.

0052 still creates the table, empty, on a new install (from its own definition); this then drops it in the same
boot. Idempotent: a database without the table (a second run) is left alone.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_task_workers_task_id")
    connection.exec_driver_sql("DROP TABLE IF EXISTS task_workers")


def downgrade_sync(connection) -> None:
    """Nothing to restore: no code reads the table, and its rows are in the upgrade backup while it is kept."""
    return
