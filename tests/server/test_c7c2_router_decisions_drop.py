"""C7c-2 (v0.1.64): migration 0073 drops `router_decisions`, the pre-turn router's audit table.

Nothing has written it since 0.1.48 and no code reads it (C7c-1 removed the model). The drop is its own
PR, after the code (v0.1.64 plan §6): code can be reverted, a table can't. Idempotent, and a database
without the table (a fresh install since C7c-1) is left alone.
"""
import sqlalchemy as sa

from server.db.migrations import runner
from server.db.migrations.versions import _0073_drop_router_decisions as m0073


def _with_table(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE router_decisions (id INTEGER PRIMARY KEY, conversation_id VARCHAR(50) NOT NULL, "
            "user_message TEXT NOT NULL, action VARCHAR(20) NOT NULL, spawn_id INTEGER, task_brief TEXT, "
            "reason TEXT, raw JSON, timestamp DATETIME)")
        conn.exec_driver_sql("CREATE INDEX ix_router_decisions_conversation_id ON router_decisions (conversation_id)")
        conn.exec_driver_sql(
            "INSERT INTO router_decisions (conversation_id, user_message, action) VALUES ('c', 'hi', 'answer')")


def _names(engine, kind):
    with engine.connect() as conn:
        return {row[0] for row in conn.exec_driver_sql(f"SELECT name FROM sqlite_master WHERE type='{kind}'")}


def test_the_table_and_its_index_are_dropped(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    _with_table(engine)
    with engine.begin() as conn:
        m0073.upgrade_sync(conn)
    assert "router_decisions" not in _names(engine, "table")
    assert "ix_router_decisions_conversation_id" not in _names(engine, "index")


def test_a_second_run_and_a_database_without_the_table_are_left_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'b.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE keep_me (id INTEGER PRIMARY KEY)")
        m0073.upgrade_sync(conn)
        m0073.upgrade_sync(conn)
    assert _names(engine, "table") == {"keep_me"}


def test_0073_is_in_the_boot_chain():
    assert ("0073", m0073.upgrade_sync) in runner.MIGRATIONS
