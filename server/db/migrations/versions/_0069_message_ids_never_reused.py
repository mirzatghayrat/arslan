"""0069: a conversation message's id is never handed out again (v0.1.63 S3b).

S3b's "undo this turn" deletes the newest messages of a conversation. Without AUTOINCREMENT SQLite
gives a new row max(id)+1, so the next message would take a deleted one's id, and what remembers ids
would misread it: the phone's seenUpTo and the window's resume (`last_message_id`) as already seen, a
summary's `up_to_message_id` as already folded in. AUTOINCREMENT needs the table rebuilt (SQLite
cannot change a primary key in place):

- 0059's full-text index and its three triggers go first, so nothing fires during the copy;
- the rows are copied with their ids into the new table (every column, the run_id foreign key with
  ON DELETE SET NULL), which takes the old name and its conversation_id index;
- the sequence starts past the highest id a row or a summary has used;
- the index and triggers come back as 0059 made them, and the index is rebuilt.

A run or spawn id that points at nothing is copied as NULL: the new table's foreign keys would refuse
it, and ON DELETE SET NULL would have cleared it. A column the model no longer has is not copied (no
code writes it). Idempotent: a table whose SQL already says AUTOINCREMENT (a fresh database gets it
from the model) is left alone. It runs in the boot transaction, after the upgrade backup.
"""
from __future__ import annotations

from ._0059_messages_fts import _STATEMENTS as _SEARCH

_COLUMNS = ("id", "conversation_id", "role", "content", "display_content", "spawn_id", "run_id",
            "timestamp", "job_outcome", "source")
_NEW = (
    "CREATE TABLE arslan_messages_0069 ("
    "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, conversation_id VARCHAR(50) NOT NULL, "
    "role VARCHAR(20) NOT NULL, content TEXT NOT NULL, display_content TEXT, spawn_id INTEGER, "
    "run_id INTEGER, timestamp DATETIME, job_outcome VARCHAR(20), source VARCHAR(20), "
    "FOREIGN KEY(spawn_id) REFERENCES spawns (id), "
    "FOREIGN KEY(run_id) REFERENCES runs (id) ON DELETE SET NULL)")
# column -> the table its id must name
_REFERENCES = {"spawn_id": "spawns", "run_id": "runs"}


def _tables(connection) -> set[str]:
    return {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def upgrade_sync(connection) -> None:
    row = connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='arslan_messages'").first()
    if row is None or "AUTOINCREMENT" in (row[0] or "").upper():
        return
    tables = _tables(connection)
    for trigger in ("arslan_messages_fts_ai", "arslan_messages_fts_ad", "arslan_messages_fts_au"):
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger}")
    connection.exec_driver_sql("DROP TABLE IF EXISTS arslan_messages_fts")
    connection.exec_driver_sql("DROP TABLE IF EXISTS arslan_messages_0069")
    connection.exec_driver_sql(_NEW)
    have = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(arslan_messages)").fetchall()}
    picked = []
    for column in _COLUMNS:
        parent = _REFERENCES.get(column)
        if column not in have or (parent and parent not in tables):
            picked.append("NULL")
        elif parent:
            picked.append(f"CASE WHEN {column} IN (SELECT id FROM {parent}) THEN {column} END")
        else:
            picked.append(column)
    connection.exec_driver_sql(f"INSERT INTO arslan_messages_0069 ({', '.join(_COLUMNS)}) "
                               f"SELECT {', '.join(picked)} FROM arslan_messages")
    connection.exec_driver_sql("DROP TABLE arslan_messages")
    connection.exec_driver_sql("ALTER TABLE arslan_messages_0069 RENAME TO arslan_messages")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_arslan_messages_conversation_id ON arslan_messages (conversation_id)")
    top = connection.exec_driver_sql("SELECT MAX(id) FROM arslan_messages").scalar() or 0
    if "arslan_summaries" in tables:
        top = max(top, connection.exec_driver_sql("SELECT MAX(up_to_message_id) FROM arslan_summaries").scalar() or 0)
    connection.exec_driver_sql("DELETE FROM sqlite_sequence WHERE name IN ('arslan_messages', 'arslan_messages_0069')")
    connection.exec_driver_sql("INSERT INTO sqlite_sequence (name, seq) VALUES ('arslan_messages', ?)", (top,))
    for statement in _SEARCH:
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql("INSERT INTO arslan_messages_fts(arslan_messages_fts) VALUES ('rebuild')")


def downgrade_sync(connection) -> None:
    """AUTOINCREMENT is harmless to older code, which reads and writes the same columns."""
    return
