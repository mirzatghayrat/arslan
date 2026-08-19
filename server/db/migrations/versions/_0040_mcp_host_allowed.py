"""0040: mcp_servers.host_allowed — server-level host consent.

User ruling 2026-08-18: connect = usable by Arslan; the per-tool
wire/host_enabled pair stops gating the HOST dimension (it remains the spawn
vocabulary). Legacy rows backfill to 1 deliberately: every existing server was
connected by a human, and connect IS the consent act under the ruling —
chronology, not a fail-open guess (same argument as 0038's NULL note).
"""
from __future__ import annotations


def _tables(connection) -> set[str]:
    return {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def upgrade_sync(connection) -> None:
    if "mcp_servers" not in _tables(connection):
        return
    existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(mcp_servers)")}
    if "host_allowed" not in existing:
        connection.exec_driver_sql(
            "ALTER TABLE mcp_servers ADD COLUMN host_allowed BOOLEAN NOT NULL DEFAULT 1")


def downgrade_sync(connection) -> None:
    """Leaving the column is harmless (unread by older code)."""
    return
