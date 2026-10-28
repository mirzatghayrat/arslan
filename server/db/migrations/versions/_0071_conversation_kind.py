"""0071: `conversation_contexts` gains `kind` and `parent_id` (v0.1.64, Q1 with SUB).

`kind` is what a conversation is, stored: `quick` for Q1's quick questions and `chat` once one is turned
into an ordinary conversation; SUB adds `sub`. NULL reads as today, worked out on each read
(`phone_reads.describe`). `parent_id` is SUB's link from a sub-session to the conversation that started it.

Add-only: two nullable columns, no data moved, so reverting the code that uses them needs nothing back.
Idempotent: a column already there is left alone, and so is a database without the table (a new install's
create_all makes it with both columns).
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "conversation_contexts" not in tables:
        return
    have = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(conversation_contexts)")}
    for name, ddl in (("kind", "VARCHAR(20)"), ("parent_id", "VARCHAR(100)")):
        if name not in have:
            connection.exec_driver_sql(f"ALTER TABLE conversation_contexts ADD COLUMN {name} {ddl}")


def downgrade_sync(connection) -> None:
    """Leaving the columns is harmless (unread by older code); SQLite before 3.35 cannot drop them."""
    return
