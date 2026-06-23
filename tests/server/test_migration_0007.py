import sqlalchemy as sa

from server.db.migrations.versions._0007_runs import downgrade_sync, upgrade_sync


def _existing_db_without_runs(conn):
    conn.execute(sa.text(
        "CREATE TABLE arslan_messages (id INTEGER PRIMARY KEY, conversation_id TEXT, "
        "role TEXT, content TEXT, display_content TEXT, spawn_id INTEGER, timestamp DATETIME)"
    ))


def test_upgrade_creates_tables_and_column():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _existing_db_without_runs(conn)
        upgrade_sync(conn)
        insp = sa.inspect(conn)
        names = set(insp.get_table_names())
        assert {"runs", "run_steps", "run_evaluations"} <= names
        cols = {c["name"] for c in insp.get_columns("arslan_messages")}
        assert "run_id" in cols


def test_upgrade_is_idempotent():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _existing_db_without_runs(conn)
        upgrade_sync(conn)
        upgrade_sync(conn)  # must not raise
        cols = {c["name"] for c in sa.inspect(conn).get_columns("arslan_messages")}
        assert "run_id" in cols
