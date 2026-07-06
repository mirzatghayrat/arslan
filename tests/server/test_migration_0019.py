"""0019: user_facts gains a nullable category column, with a working downgrade."""
import sqlite3
import pytest
from sqlalchemy import create_engine, inspect


@pytest.fixture
def old_db(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE user_facts (id INTEGER PRIMARY KEY, content TEXT NOT NULL, "
        "source VARCHAR(20), sensitive BOOLEAN, created_at DATETIME);"
        "INSERT INTO user_facts (id, content) VALUES (5, 'hi'), (9, 'yo');"
    )
    con.commit()
    con.close()
    return path


def _run(path, fn):
    from server.db.migrations.versions import _0019_fact_category as m
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        getattr(m, fn)(conn)
    return engine


def test_upgrade_adds_category_nullable_idempotent(old_db):
    engine = _run(old_db, "upgrade_sync")
    cols = {c["name"]: c for c in inspect(engine).get_columns("user_facts")}
    assert "category" in cols and cols["category"]["nullable"] is True
    _run(old_db, "upgrade_sync")  # idempotent, no raise
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT category FROM user_facts WHERE id=5").fetchone()[0] is None


def test_downgrade_drops_category_preserving_rows(old_db):
    _run(old_db, "upgrade_sync")
    engine = _run(old_db, "downgrade_sync")
    cols = {c["name"] for c in inspect(engine).get_columns("user_facts")}
    assert "category" not in cols
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT id, content FROM user_facts ORDER BY id").fetchall()
        assert rows == [(5, "hi"), (9, "yo")]
