"""0050: durable exclusion from scoring, learning and replay corpora."""


def upgrade_sync(connection):
    tables = {r[0] for r in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "runs" not in tables:
        return
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)")}
    if "no_learning" not in columns:
        connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN no_learning BOOLEAN NOT NULL DEFAULT 0")
    # Older archives did not have this flag when the restore guard was applied.
    if "memory_restore_sources" in tables:
        connection.exec_driver_sql("""UPDATE runs SET no_learning=1 WHERE CAST(id AS TEXT) IN
            (SELECT source_id FROM memory_restore_sources WHERE source_kind='run_id')""")
