"""0083: `conversation_seen`, the newest message the user has seen in each conversation (v0.1.64, INB4).

A reply that came without an error, or a background job done, newer than this mark reads "done, not seen" in the window's
sidebar; opening the conversation moves the mark (`POST /conversations/{id}/seen`). Kept in the database so a restart keeps
it. A table of its own: not every conversation has a `conversation_contexts` row.

An upgrade starts with every conversation seen up to its newest message, at that message's time: replies from before INB4 are
not news (#589 F1). create_all makes the empty table before the migrations run, so the marks are written here, whether the
table was there or not; one already there is kept.

Add-only: a new table and its first marks; reverting the code that reads it needs nothing back. Idempotent.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS conversation_seen ("
        "conversation_id VARCHAR(100) NOT NULL PRIMARY KEY, "
        "seen_message_id INTEGER NOT NULL DEFAULT 0, "
        "seen_at DATETIME NOT NULL)")
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "arslan_messages" in tables:
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO conversation_seen (conversation_id, seen_message_id, seen_at) "
            "SELECT conversation_id, MAX(id), COALESCE(MAX(timestamp), CURRENT_TIMESTAMP) FROM arslan_messages "
            "GROUP BY conversation_id")


def downgrade_sync(connection) -> None:
    """Leaving the table is harmless: older code never reads it."""
    return
