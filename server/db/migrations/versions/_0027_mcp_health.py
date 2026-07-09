"""0027: MCP equipment health-check columns on mcp_servers (PB-4).

health_status: "ok" | "failing" | NULL (never checked).
last_checked_at: when the last on-demand probe ran.
"""


_COLUMNS = [
    ("last_checked_at", "DATETIME"),
    ("health_status", "VARCHAR(20)"),
]


def upgrade_sync(connection) -> None:
    existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(mcp_servers)")}
    for name, ddl in _COLUMNS:
        if name not in existing:
            connection.exec_driver_sql(f"ALTER TABLE mcp_servers ADD COLUMN {name} {ddl}")


def downgrade_sync(connection) -> None:
    # SQLite pre-3.35 cannot DROP COLUMN; best-effort for newer versions.
    for name, _ in _COLUMNS:
        try:
            connection.exec_driver_sql(f"ALTER TABLE mcp_servers DROP COLUMN {name}")
        except Exception:  # noqa: BLE001 — downgrade is best-effort on old SQLite
            pass
