"""0097 (ASK1-b, v0.1.64): a scheduled task's fire runs commands in the sandbox, from what its prompt's turn had read.

`scheduled_tasks.outside_seen` records whether the turn that wrote or last changed a task's prompt had read outside
content; a fire starts from it (scheduler._fire), and true means its commands run offline. It replaces the S64-0 rule
that every fire started as having read outside content. Rows from before this migration become true, because nobody
knows what their turns read: existing tasks run their commands sandboxed and offline. Only the schedule tool sets it
afterwards, and nothing clears it.

On an install that existed before this boot (runner.EXISTED_BEFORE_THIS_BOOT, read as 0095 reads it; called on its
own, an install counts as existing) it also sets `scheduled_commands_note = pending`: the Scheduled page says once
that scheduled tasks may now run commands in the sandbox and that anything that would ask is refused and listed, and
the window writes `seen`. A new install gets no note.

Idempotent: a column already there is left alone with its rows (a new install's create_all makes it), the note is set
only where the key is missing (a `seen` stays seen), and a database without either table is left alone.
"""
from __future__ import annotations

#: runner.EXISTED_BEFORE_THIS_BOOT (the runner imports this module, so the name is repeated, not imported).
_EXISTED = "database_existed_before_this_boot"


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "scheduled_tasks" in tables:
        have = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(scheduled_tasks)")}
        if "outside_seen" not in have:
            connection.exec_driver_sql(
                "ALTER TABLE scheduled_tasks ADD COLUMN outside_seen BOOLEAN NOT NULL DEFAULT 0")
            connection.exec_driver_sql("UPDATE scheduled_tasks SET outside_seen = 1")
    if "settings" in tables and connection.info.get(_EXISTED, True):
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('scheduled_commands_note', 'pending')")


def downgrade_sync(connection) -> None:
    """Leaving the column and the key is harmless: older code reads neither."""
    return
