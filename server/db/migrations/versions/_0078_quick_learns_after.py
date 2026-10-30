"""0078: `conversation_contexts.learns_after_message_id`, where a turned quick question starts to learn
(v0.1.64, Q1 #3).

The user decided on 2026-10-29 that a quick question turned into a chat learns like an ordinary conversation
from then on, and that its quick turns before that never teach. Turning it stores the id of its last message
here; the facts extractor reads only the user's messages after it. NULL is every other conversation: all of
its messages, as before.

Add-only: one nullable column, no data moved, so reverting the code that uses it needs nothing back.
Idempotent: a column already there is left alone, and so is a database without the table (a new install's
create_all makes it with the column).
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "conversation_contexts" not in tables:
        return
    have = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(conversation_contexts)")}
    if "learns_after_message_id" not in have:
        connection.exec_driver_sql("ALTER TABLE conversation_contexts ADD COLUMN learns_after_message_id INTEGER")


def downgrade_sync(connection) -> None:
    """Leaving the column is harmless (unread by older code); SQLite before 3.35 cannot drop it."""
    return
