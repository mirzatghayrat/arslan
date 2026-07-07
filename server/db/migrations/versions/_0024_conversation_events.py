"""0024: conversation_events (growth timeline)."""


def upgrade_sync(connection) -> None:
    names = {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "conversation_events" not in names:
        connection.exec_driver_sql(
            "CREATE TABLE conversation_events ("
            "id INTEGER PRIMARY KEY, conversation_id VARCHAR(50) NOT NULL, "
            "kind VARCHAR(20) NOT NULL, ref JSON, summary TEXT NOT NULL DEFAULT '', "
            "created_at DATETIME)")
        connection.exec_driver_sql(
            "CREATE INDEX ix_conversation_events_conversation_id ON conversation_events (conversation_id)")
        connection.exec_driver_sql(
            "CREATE INDEX ix_conversation_events_created_at ON conversation_events (created_at)")


def downgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS conversation_events")
