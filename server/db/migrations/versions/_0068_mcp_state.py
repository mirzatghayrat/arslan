"""0068: one state per MCP server, and each tool's hints (0.1.61 §B1, §B4).

`state` replaces three vocabularies (status, health_status, the capability rows' on/off/setup):
off | starting | ready | failed | needs_auth | parked, with when it was entered (`state_at`), when
the server last answered (`last_ok_at`), when it will be tried again (`next_retry_at`) and how many
plans in a row failed (`fail_count`). Existing rows: host access off → off; connected → ready;
error → failed; anything else → starting. The supervisor resets every enabled row to `starting` at
boot anyway — a `ready` from an earlier process is never trusted. `status` stays and is kept in step
for the old UI until PR 8. `tools.annotations` holds the hints the server declared (readOnlyHint,
destructiveHint, idempotentHint, openWorldHint, title). Idempotent; a database without the tables
is left alone.
"""
from __future__ import annotations

_SERVER_COLUMNS = (
    ("state", "VARCHAR(20) NOT NULL DEFAULT 'starting'"),
    ("state_at", "DATETIME"),
    ("last_ok_at", "DATETIME"),
    ("next_retry_at", "DATETIME"),
    ("fail_count", "INTEGER NOT NULL DEFAULT 0"),
)


def _tables(connection) -> set[str]:
    return {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}


def upgrade_sync(connection) -> None:
    tables = _tables(connection)
    if "mcp_servers" in tables:
        have = _columns(connection, "mcp_servers")
        for name, ddl in _SERVER_COLUMNS:
            if name not in have:
                connection.exec_driver_sql(f"ALTER TABLE mcp_servers ADD COLUMN {name} {ddl}")
        if "state" not in have:
            connection.exec_driver_sql(
                "UPDATE mcp_servers SET state = CASE"
                " WHEN host_allowed = 0 THEN 'off'"
                " WHEN status = 'connected' THEN 'ready'"
                " WHEN status = 'error' THEN 'failed'"
                " ELSE 'starting' END")
    if "tools" in tables and "annotations" not in _columns(connection, "tools"):
        connection.exec_driver_sql("ALTER TABLE tools ADD COLUMN annotations JSON")


def downgrade_sync(connection) -> None:
    """Leaving the columns is harmless (unread by older code); SQLite before 3.35 cannot drop them."""
    return
