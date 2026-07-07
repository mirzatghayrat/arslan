"""0023: structured injected-KB sources on runs (detail-page chips)."""


def upgrade_sync(connection) -> None:
    existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)")}
    if "injected_kb_sources" not in existing:
        connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN injected_kb_sources TEXT")


def downgrade_sync(connection) -> None:
    try:
        connection.exec_driver_sql("ALTER TABLE runs DROP COLUMN injected_kb_sources")
    except Exception:  # noqa: BLE001
        pass
