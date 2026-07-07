"""0022: index runs.created_at for time-window catalog/anomaly queries."""


def upgrade_sync(connection) -> None:
    existing = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(runs)")}
    if "ix_runs_created_at" not in existing:
        connection.exec_driver_sql("CREATE INDEX ix_runs_created_at ON runs (created_at)")


def downgrade_sync(connection) -> None:
    try:
        connection.exec_driver_sql("DROP INDEX ix_runs_created_at")
    except Exception:  # noqa: BLE001 — best-effort
        pass
