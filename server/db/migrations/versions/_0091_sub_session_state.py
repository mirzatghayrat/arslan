"""0091: `conversation_contexts.sub_state`, what a sub-session owes its parent, for a restart (v0.1.64, SUB5a).

A sub-session's report waits for its parent's summary turn in memory (SUB4), and a queued sub-session has no task row
yet, so after a restart neither says that its parent was still waiting. This column is written when that changes
(`sub_sessions`): `working` when the sub-session is made, `summing` once a summary turn that holds its report runs,
cleared when that summary ends, and `interrupted` by the boot pass for one a restart cut short. Boot only reads it.

Add-only: one nullable text column, no data moved, so reverting the code that uses it needs nothing back.
Idempotent: a column already there is left alone, and so is a database without the table (a new install's
create_all makes it with the column).
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "conversation_contexts" not in tables:
        return
    have = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(conversation_contexts)")}
    if "sub_state" not in have:
        connection.exec_driver_sql("ALTER TABLE conversation_contexts ADD COLUMN sub_state VARCHAR(20)")


def downgrade_sync(connection) -> None:
    """Leaving the column is harmless (unread by older code); SQLite before 3.35 cannot drop it."""
    return
