import sqlalchemy as sa

from server.db.migrations.versions._0009_knowledge import upgrade_sync


def test_upgrade_creates_table_and_fts():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        upgrade_sync(conn)
        names = set(sa.inspect(conn).get_table_names())
        assert "knowledge_chunks" in names
        conn.exec_driver_sql(
            "INSERT INTO knowledge_chunks (spawn_id, source, chunk_index, text) "
            "VALUES (1, 's', 0, 'alpha beta gamma')"
        )
        rid = conn.exec_driver_sql("SELECT id FROM knowledge_chunks").scalar()
        conn.exec_driver_sql(
            "INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (?, ?)",
            (rid, "alpha beta gamma"),
        )
        hit = conn.exec_driver_sql(
            "SELECT text FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH 'beta'"
        ).scalar()
        assert hit == "alpha beta gamma"


def test_upgrade_idempotent():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        upgrade_sync(conn)
        upgrade_sync(conn)
        assert "knowledge_chunks" in set(sa.inspect(conn).get_table_names())
