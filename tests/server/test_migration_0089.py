"""0089 (v0.1.64, CAP7a): capability_sources' kind CHECK widens to allow 'plugin' (CAP7b stores a plugin as
one source). The table is rebuilt from its own live CREATE text with only that clause changed, so the result
is the old schema apart from the CHECK and matches a fresh database from the model; rows are copied as they
are; nothing else changes.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa

from server.db.migrations import runner
from server.db.migrations.versions import _0089_capability_sources_plugin_kind as m0089
from server.db.models import CapabilitySource
from server.db.session import build_engine
from server.services import storage_boot

NEW = "kind IN ('mcp','skill','plugin')"
OLD = "kind IN ('mcp','skill')"


def _model_sql() -> str:
    """capability_sources exactly as the model builds it today (the widened CHECK)."""
    engine = sa.create_engine("sqlite://")
    try:
        CapabilitySource.__table__.create(engine)
        with engine.connect() as conn:
            return _table_sql(conn)
    finally:
        engine.dispose()


def _table_sql(conn) -> str:
    return conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='capability_sources'").scalar()


def _schema(sql: str) -> list[str]:
    """A CREATE statement as compared columns/constraints: SQLite quotes the table name on RENAME, so ignore
    quoting and whitespace."""
    return sql.replace('"', "").split()


def _insert(i: int, kind: str) -> str:
    return ("INSERT INTO capability_sources (id, owner_id, kind, name, candidate_id, needs, grants, state, "
            f"created_at) VALUES ('id{i}', 'local', '{kind}', 'n{i}', 'c{i}', '{{}}', '{{}}', 'installed', "
            "'2026-01-01 00:00:00')")


def _old_db(path) -> tuple[str, str]:
    """An existing database whose capability_sources still has the pre-0089 CHECK, with three rows."""
    model_sql = _model_sql()
    old_sql = model_sql.replace(NEW, OLD)
    assert old_sql != model_sql and old_sql.count(OLD) == 1       # the only difference is the kind CHECK
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(old_sql)
            for i, kind in enumerate(("mcp", "skill", "mcp")):
                conn.exec_driver_sql(_insert(i, kind))
    finally:
        engine.dispose()
    return old_sql, model_sql


def test_only_the_kind_check_changes_and_every_row_is_preserved(tmp_path):
    db = tmp_path / "old.db"
    old_sql, model_sql = _old_db(db)
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            assert _table_sql(conn) == old_sql                   # precondition: the old CHECK
            before = [tuple(r) for r in conn.exec_driver_sql("SELECT * FROM capability_sources ORDER BY id")]
            m0089.upgrade_sync(conn)
            after_sql = _table_sql(conn)
            after = [tuple(r) for r in conn.exec_driver_sql("SELECT * FROM capability_sources ORDER BY id")]
        assert _schema(after_sql) == _schema(old_sql.replace(OLD, NEW))   # schema identical apart from the CHECK
        assert _schema(after_sql) == _schema(model_sql)          # and the same as a fresh database from the model
        assert NEW in after_sql                                  # the kind CHECK is the widened one
        assert len(after) == len(before) == 3                    # row count unchanged
        assert after == before                                   # row for row unchanged
    finally:
        engine.dispose()


def test_plugin_is_rejected_before_and_accepted_after(tmp_path):
    db = tmp_path / "old.db"
    _old_db(db)
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            with pytest.raises(sa.exc.IntegrityError):           # the old CHECK enforces mcp/skill
                conn.exec_driver_sql(_insert(9, "plugin"))
        with engine.begin() as conn:
            m0089.upgrade_sync(conn)
        with engine.begin() as conn:
            conn.exec_driver_sql(_insert(9, "plugin"))           # now allowed
            assert conn.exec_driver_sql(
                "SELECT kind FROM capability_sources WHERE id='id9'").scalar() == "plugin"
    finally:
        engine.dispose()


def test_idempotent_on_a_widened_or_fresh_table(tmp_path):
    db = tmp_path / "old.db"
    _old_db(db)
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            m0089.upgrade_sync(conn)
            once = _table_sql(conn)
            m0089.upgrade_sync(conn)                             # a re-run leaves it alone
            assert _table_sql(conn) == once
    finally:
        engine.dispose()
    fresh = sa.create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        CapabilitySource.__table__.create(fresh)                 # already has 'plugin'
        with fresh.begin() as conn:
            before = _table_sql(conn)
            m0089.upgrade_sync(conn)
            assert _table_sql(conn) == before
    finally:
        fresh.dispose()


async def test_on_an_existing_database_at_0086_the_boot_applies_0089(tmp_path):
    """Boot the way the app boots, roll capability_sources back to the pre-0089 state (an install stopped at
    0086), and boot again: the runner reapplies 0089, widening the CHECK and keeping the rows."""
    db = tmp_path / "boot.db"
    engine = build_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()
    sync = sa.create_engine(f"sqlite:///{db}")
    try:
        with sync.begin() as conn:
            assert NEW in _table_sql(conn)                       # a fresh boot already allows plugin
            old_sql = _table_sql(conn).replace(NEW, OLD)
            conn.exec_driver_sql("DROP TABLE capability_sources")
            conn.exec_driver_sql(old_sql)                        # back to the 0086 table
            conn.exec_driver_sql(_insert(1, "mcp"))
            conn.exec_driver_sql("DELETE FROM schema_version WHERE version = '0089'")
    finally:
        sync.dispose()
    engine = build_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await storage_boot.initialize(engine)                    # the existing install upgrades
    finally:
        await engine.dispose()
    sync = sa.create_engine(f"sqlite:///{db}")
    try:
        with sync.begin() as conn:
            assert NEW in _table_sql(conn)
            assert ("0089",) in [tuple(r) for r in conn.exec_driver_sql("SELECT version FROM schema_version")]
            assert conn.exec_driver_sql("SELECT kind FROM capability_sources WHERE id='id1'").scalar() == "mcp"
            conn.exec_driver_sql(_insert(2, "plugin"))           # and plugin is accepted end to end
    finally:
        sync.dispose()


def test_0089_is_registered_in_the_runner():
    assert "0089" in [vid for vid, _ in runner.MIGRATIONS]
