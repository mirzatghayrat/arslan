"""0021: detailed-replay columns on runs (model/provider/tokens/error/prompt/kb)."""


_COLUMNS = [
    ("model", "VARCHAR(80)"),
    ("provider", "VARCHAR(40)"),
    ("tokens_in", "INTEGER"),
    ("tokens_out", "INTEGER"),
    ("tokens_estimated", "BOOLEAN NOT NULL DEFAULT 0"),
    ("error_kind", "VARCHAR(60)"),
    ("error_text", "TEXT"),
    ("system_prompt", "TEXT"),
    ("injected_kb", "TEXT"),
]


def upgrade_sync(connection) -> None:
    existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)")}
    for name, ddl in _COLUMNS:
        if name not in existing:
            connection.exec_driver_sql(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")


def downgrade_sync(connection) -> None:
    # SQLite pre-3.35 cannot DROP COLUMN; best-effort for newer versions.
    for name, _ in _COLUMNS:
        try:
            connection.exec_driver_sql(f"ALTER TABLE runs DROP COLUMN {name}")
        except Exception:  # noqa: BLE001 — downgrade is best-effort on old SQLite
            pass
