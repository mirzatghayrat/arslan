"""0084: `scheduled_tasks.seen_at`, when you last opened a scheduled task (v0.1.64, INB5).

A run of the task that could not ask you something (a `policy` entry in the approval ledger) waits on you while it is newer
than this mark (progress.waiting_on_user). Opening the task on the Scheduled page sets it
(`POST /scheduled-tasks/{id}/seen`). The mark is the task's own column rather than a row in `conversation_seen` keyed by a
made-up id: a conversation id can be almost any string, so no key there is safe from colliding with one (#589 review nit,
#590 review F4), and the mark goes away with its task.

Add-only: one nullable column, no data moved, so reverting the code that uses it needs nothing back. Idempotent: a column
already there is left alone, and so is a database without the table (a new install's create_all makes it with the column).
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "scheduled_tasks" not in tables:
        return
    have = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(scheduled_tasks)")}
    if "seen_at" not in have:
        connection.exec_driver_sql("ALTER TABLE scheduled_tasks ADD COLUMN seen_at DATETIME")


def downgrade_sync(connection) -> None:
    """Leaving the column is harmless (unread by older code); SQLite before 3.35 cannot drop it."""
    return
