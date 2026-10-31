"""0083: `conversation_seen`, the newest message the user has seen in each conversation (v0.1.64, INB4).

A reply that came without an error, or a background job done, newer than this mark reads "done, not seen" in the window's
sidebar; opening the conversation moves the mark (`POST /conversations/{id}/seen`). Kept in the database so a restart keeps
it. A table of its own: not every conversation has a `conversation_contexts` row.

Add-only: a new table, no data moved; reverting the code that reads it needs nothing back. Idempotent: a table already there
is left alone (a new install's create_all makes it).
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS conversation_seen ("
        "conversation_id VARCHAR(100) NOT NULL PRIMARY KEY, "
        "seen_message_id INTEGER NOT NULL DEFAULT 0, "
        "seen_at DATETIME NOT NULL)")


def downgrade_sync(connection) -> None:
    """Leaving the table is harmless: older code never reads it."""
    return
