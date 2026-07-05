"""0018: old-shape knowledge_chunks is rebuilt (spawn_id nullable + new cols), idempotent."""
import sqlite3

import pytest
from sqlalchemy import create_engine, inspect


@pytest.fixture
def old_db(tmp_path):
    """A DB with the 0009-shape knowledge_chunks + one row + FTS row."""
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE spawns (id INTEGER PRIMARY KEY);
        CREATE TABLE collections (
            id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL,
            description TEXT, created_at DATETIME);
        CREATE TABLE knowledge_chunks (
            id INTEGER PRIMARY KEY,
            spawn_id INTEGER NOT NULL REFERENCES spawns(id) ON DELETE CASCADE,
            source VARCHAR(200) NOT NULL, chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL, created_at DATETIME);
        CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(text);
        INSERT INTO spawns (id) VALUES (1);
        INSERT INTO knowledge_chunks (id, spawn_id, source, chunk_index, text)
            VALUES (42, 1, 's.txt', 0, 'hello world');
        INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (42, 'hello world');
        """
    )
    con.commit()
    con.close()
    return path


def _upgrade(path):
    from server.db.migrations.versions._0018_second_brain import upgrade_sync
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        upgrade_sync(conn)
    return engine


def test_rebuild_preserves_ids_and_adds_columns(old_db):
    engine = _upgrade(old_db)
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("knowledge_chunks")}
    assert {"collection_id", "embedding", "embedding_model"} <= set(cols)
    assert cols["spawn_id"]["nullable"] is True
    with engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT id, spawn_id, text FROM knowledge_chunks").fetchone()
        assert row == (42, 1, "hello world")  # id preserved → FTS rowid mapping intact
        fts = conn.exec_driver_sql(
            "SELECT kc.id FROM knowledge_chunks_fts f "
            "JOIN knowledge_chunks kc ON kc.id = f.rowid "
            "WHERE f.text MATCH 'hello'").fetchone()
        assert fts == (42,)
        fk = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        assert fk == []


def test_upgrade_idempotent(old_db):
    _upgrade(old_db)
    engine = _upgrade(old_db)  # second run = no-op, must not raise
    with engine.connect() as conn:
        n = conn.exec_driver_sql("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        assert n == 1


def test_check_constraint_enforced(old_db):
    engine = _upgrade(old_db)
    import sqlalchemy.exc
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO knowledge_chunks (spawn_id, collection_id, source, chunk_index, text) "
                "VALUES (NULL, NULL, 'x', 0, 'y')")
