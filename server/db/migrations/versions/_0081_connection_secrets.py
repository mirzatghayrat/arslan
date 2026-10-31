"""0081: a connection's moved secrets get their own encrypted column (v0.1.64 SEC1, docs/plans/0164/CAPX-followups.md).

A secret typed into a connection's address or command arguments can move out, leaving a `${NAME}` placeholder
(server/services/connection_secrets.py). Its value goes into `mcp_servers.secrets`: a JSON object of name -> value,
encrypted with the same crypto as `env`, and filled back in when the connection starts. Not `env`: for an HTTP
connection that is its header map, so a secret there would also go out as a header.

Adds one nullable column and drops nothing. Idempotent: a database that has the column, or no mcp_servers table,
is left alone.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "mcp_servers" not in tables:
        return
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(mcp_servers)")}
    if "secrets" not in columns:
        connection.exec_driver_sql("ALTER TABLE mcp_servers ADD COLUMN secrets TEXT")


def downgrade_sync(connection) -> None:
    """Nothing to undo here. An older build refuses this database at boot (runner.assert_supported_schema does not
    know 0081) and runs only on its own upgrade backup, so it never reads the column. Moving a secret back into the
    address or arguments is not offered yet (SEC1b's card)."""
    return
