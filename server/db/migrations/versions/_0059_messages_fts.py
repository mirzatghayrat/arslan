"""0059: full-text search over the conversation history (0.1.52 S3).

FTS5 with the `trigram` tokenizer (substring matches, so Chinese works without word
segmentation; SQLite >= 3.34), as an external-content index on arslan_messages kept
in step by triggers, plus a one-time rebuild for the history already there.
Idempotent; a fresh database gets it through the migration chain.
"""
from __future__ import annotations

_STATEMENTS = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS arslan_messages_fts USING fts5("
    "content, content='arslan_messages', content_rowid='id', tokenize='trigram')",
    "CREATE TRIGGER IF NOT EXISTS arslan_messages_fts_ai AFTER INSERT ON arslan_messages BEGIN "
    "INSERT INTO arslan_messages_fts(rowid, content) VALUES (new.id, new.content); END",
    "CREATE TRIGGER IF NOT EXISTS arslan_messages_fts_ad AFTER DELETE ON arslan_messages BEGIN "
    "INSERT INTO arslan_messages_fts(arslan_messages_fts, rowid, content) VALUES ('delete', old.id, old.content); END",
    "CREATE TRIGGER IF NOT EXISTS arslan_messages_fts_au AFTER UPDATE OF content ON arslan_messages BEGIN "
    "INSERT INTO arslan_messages_fts(arslan_messages_fts, rowid, content) VALUES ('delete', old.id, old.content); "
    "INSERT INTO arslan_messages_fts(rowid, content) VALUES (new.id, new.content); END",
)


def upgrade_sync(connection) -> None:
    existed = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arslan_messages_fts'").first()
    for statement in _STATEMENTS:
        connection.exec_driver_sql(statement)
    if not existed:
        connection.exec_driver_sql("INSERT INTO arslan_messages_fts(arslan_messages_fts) VALUES ('rebuild')")


def downgrade_sync(connection) -> None:
    for name in ("arslan_messages_fts_ai", "arslan_messages_fts_ad", "arslan_messages_fts_au"):
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
    connection.exec_driver_sql("DROP TABLE IF EXISTS arslan_messages_fts")
