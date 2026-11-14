"""0099 (SIDE-1, v0.1.64): where a side chat branches from its parent, and whether it started marked.

A side chat is a `conversation_contexts` row of kind `side` with its parent (0071's columns). Two nullable columns there,
written once when it is made (`side_chats.create`) and never changed:
- `branch_message_id`: the parent's message it branched at; it reads its parent up to there (message ids are never
  handed out twice, 0069);
- `outside_at_start`: whether what it reads of its parent took in outside content (card, rule 3); NULL counts as yes.
The quote the user selected is not stored: it is the side chat's first message (⓪Plan, 2026-11-14).

Add-only, so reverting the code that uses them needs nothing back. Idempotent: a column already there is left alone, and
so is a database without the table (a new install's create_all makes it with both). Numbered 0099 (docs/sessions.md
§4; 0093 was released): it goes last in `MIGRATIONS`, after 0095, while 0096-0098 stay reserved.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "conversation_contexts" not in tables:
        return
    have = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(conversation_contexts)")}
    if "branch_message_id" not in have:
        connection.exec_driver_sql("ALTER TABLE conversation_contexts ADD COLUMN branch_message_id INTEGER")
    if "outside_at_start" not in have:
        connection.exec_driver_sql("ALTER TABLE conversation_contexts ADD COLUMN outside_at_start BOOLEAN")


def downgrade_sync(connection) -> None:
    """Leaving the columns is harmless (unread by older code); SQLite before 3.35 cannot drop them."""
    return
