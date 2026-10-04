"""0061: where a user message came from (mobile bridge §6.1).

`arslan_messages.source` is NULL for the window (every existing row) and "phone" for a message
the Arslan Bridge forwarded from a paired iPhone, so the conversation can show "from iPhone".
Idempotent; fresh databases get the column from Base.metadata.create_all. Numbered with the
0.1.53 Hands branch, which adds no migration.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(arslan_messages)")}
    if "source" not in columns:
        connection.exec_driver_sql("ALTER TABLE arslan_messages ADD COLUMN source VARCHAR(20)")


def downgrade_sync(connection) -> None:
    connection.exec_driver_sql("ALTER TABLE arslan_messages DROP COLUMN source")
