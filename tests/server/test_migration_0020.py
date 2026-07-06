"""migration 0020: add nullable user_facts.label + working downgrade."""
import sqlite3
import tempfile

from sqlalchemy import create_engine, inspect

from server.db.migrations.versions import _0020_fact_label as m


def _cols(engine):
    return {c["name"] for c in inspect(engine).get_columns("user_facts")}


def test_upgrade_adds_label_nullable_idempotent():
    p = tempfile.mktemp(suffix=".db")
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE user_facts(id INTEGER PRIMARY KEY, content TEXT, category TEXT);"
        "INSERT INTO user_facts(id, content) VALUES (5, 'hi'), (9, 'yo');")
    con.commit()
    con.close()
    e = create_engine("sqlite:///" + p)
    with e.begin() as c:
        m.upgrade_sync(c)
    assert "label" in _cols(e)
    with e.begin() as c:  # idempotent
        m.upgrade_sync(c)
    assert "label" in _cols(e)


def test_downgrade_drops_label_preserving_rows():
    p = tempfile.mktemp(suffix=".db")
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE user_facts(id INTEGER PRIMARY KEY, content TEXT, category TEXT, label TEXT);"
        "INSERT INTO user_facts(id, content) VALUES (5, 'hi'), (9, 'yo');")
    con.commit()
    con.close()
    e = create_engine("sqlite:///" + p)
    with e.begin() as c:
        m.downgrade_sync(c)
    assert "label" not in _cols(e)
    with e.connect() as c:
        rows = list(c.exec_driver_sql("SELECT id, content FROM user_facts ORDER BY id"))
    assert rows == [(5, "hi"), (9, "yo")]
