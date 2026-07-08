"""0026: hand-written notes + notes_fts (Second Brain notes layer)."""


def upgrade_sync(connection) -> None:
    names = {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "notes" not in names:
        connection.exec_driver_sql(
            "CREATE TABLE notes ("
            "id INTEGER PRIMARY KEY, title VARCHAR(200) NOT NULL, content TEXT NOT NULL DEFAULT '', "
            "tags JSON, created_at DATETIME, updated_at DATETIME)")
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")


def downgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS notes_fts")
    connection.exec_driver_sql("DROP TABLE IF EXISTS notes")
