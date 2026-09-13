"""0045: shared execution-budget snapshot; null means a pre-budget Run."""


def upgrade_sync(connection):
    tables = {r[0] for r in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "runs" not in tables:
        return
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)")}
    if "execution_budget" not in columns:
        connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN execution_budget JSON")
