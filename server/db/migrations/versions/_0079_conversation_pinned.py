"""0079: `conversation_contexts.pinned`, a conversation pinned to the top of the sidebar (v0.1.64, SB1-2).

The pin lives on the server's conversation record, so a reinstall keeps it and the iPhone can read it later
(SB1 card). It is set by its own route (`PUT /conversations/{id}/pin`), never by the context PUT, which
replaces every field and bumps `version`.

Add-only: one boolean column, default false, no data moved, so reverting the code that uses it needs nothing
back. Idempotent: a column already there is left alone, and so is a database without the table (a new
install's create_all makes it with the column).
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "conversation_contexts" not in tables:
        return
    have = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(conversation_contexts)")}
    if "pinned" not in have:
        connection.exec_driver_sql("ALTER TABLE conversation_contexts ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT 0")


def downgrade_sync(connection) -> None:
    """Leaving the column is harmless (unread by older code); SQLite before 3.35 cannot drop it."""
    return
