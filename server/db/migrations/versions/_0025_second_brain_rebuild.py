"""0025: Second Brain rebuild — user_facts.confidence + learnings(+FTS) + brain_usage.

Each object is guarded independently (not nested) so a partially-applied DB — e.g.
the base table present but its FTS shadow missing — self-heals on the next boot."""


def upgrade_sync(connection) -> None:
    cols = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(user_facts)")}
    if "confidence" not in cols:
        connection.exec_driver_sql(
            "ALTER TABLE user_facts ADD COLUMN confidence FLOAT DEFAULT 0.6")

    names = {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}

    if "learnings" not in names:
        connection.exec_driver_sql(
            "CREATE TABLE learnings ("
            "id INTEGER PRIMARY KEY, content TEXT NOT NULL, label VARCHAR(60), "
            "source_kind VARCHAR(20) NOT NULL, source_ref JSON NOT NULL, "
            "spawn_id INTEGER, confidence FLOAT DEFAULT 0.6, created_at DATETIME)")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_learnings_spawn_id ON learnings (spawn_id)")
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")

    if "brain_usage" not in names:
        connection.exec_driver_sql(
            "CREATE TABLE brain_usage ("
            "id INTEGER PRIMARY KEY, kind VARCHAR(20) NOT NULL, ref_key VARCHAR(300) NOT NULL, "
            "usage_count INTEGER NOT NULL DEFAULT 0, last_used_at DATETIME, "
            "last_used_ref VARCHAR(100), created_at DATETIME)")
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_brain_usage_kind_ref ON brain_usage (kind, ref_key)")


def downgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS brain_usage")
    connection.exec_driver_sql("DROP TABLE IF EXISTS learnings_fts")
    connection.exec_driver_sql("DROP TABLE IF EXISTS learnings")
