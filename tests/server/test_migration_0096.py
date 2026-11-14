"""0096 (v0.1.64 SUB6b): the professional methods' tables go.

SUB6b deleted the methods, their editor, their routes and their two models. 0052 now creates the two tables
from its own definitions (not the deleted models), so a new install still runs every migration, and 0096 drops
them in the same boot. An install that ran 0095 with methods stored (the defaults and a saved revision) loses
both tables on its next boot, after the upgrade backup.

Booted the way the app boots (storage_boot.initialize on build_engine).
"""
from __future__ import annotations

import sqlite3
import zipfile
from contextlib import closing

import sqlalchemy as sa

from server.db.migrations import runner
from server.db.migrations.versions import _0052_task_workers as m0052
from server.db.migrations.versions import _0096_drop_professional_methods as m0096
from server.db.session import build_engine
from server.services import storage_boot

TABLES = {"professional_methods", "professional_method_versions"}


async def _boot(db_path) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()


def _rows(db_path, query) -> list[tuple]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.exec_driver_sql(query)]
    finally:
        engine.dispose()


def _tables(db_path) -> set[str]:
    return {name for (name,) in _rows(db_path, "SELECT name FROM sqlite_master WHERE type='table'")}


def _versions(db_path) -> set[str]:
    return {version for (version,) in _rows(db_path, "SELECT version FROM schema_version")}


async def _at_0095_with_methods(db_path) -> None:
    """An install as main left it before SUB6b: every migration through 0095 recorded, 0096 not, and both
    method tables holding the defaults and one saved revision."""
    await _boot(db_path)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            for statement in m0052._METHODS:                          # the tables as 0052 made them
                conn.exec_driver_sql(statement)
            conn.exec_driver_sql("DELETE FROM schema_version WHERE version = '0096'")
            for key, revision in (("research", 2), ("apple-growth", 1), ("product-design", 1)):
                conn.exec_driver_sql(f"INSERT INTO professional_methods (key, current_revision) "
                                     f"VALUES ('{key}', {revision})")
                for number in range(1, revision + 1):
                    conn.exec_driver_sql(
                        "INSERT INTO professional_method_versions (key, revision, name, instructions, created_at) "
                        f"VALUES ('{key}', {number}, 'n{number}', 'i', '2026-10-27 09:00:00')")
    finally:
        engine.dispose()
    assert TABLES <= _tables(db_path)
    assert _versions(db_path) == {vid for vid, _ in runner.MIGRATIONS} - {"0096"}
    assert _rows(db_path, "SELECT count(*) FROM professional_method_versions") == [(4,)]


def test_0096_runs_right_after_0095_in_the_boot_chain():
    ids = [vid for vid, _ in runner.MIGRATIONS]
    assert ids == sorted(ids)
    assert runner.MIGRATIONS[ids.index("0095") + 1] == ("0096", m0096.upgrade_sync)


def test_0052_no_longer_imports_the_deleted_models():
    source = open(m0052.__file__, encoding="utf-8").read()
    assert "worker_models" not in source and "ProfessionalMethod" not in source
    assert m0052._TASK_WORKERS                                       # SUB7's table stays defined here


async def test_a_new_install_runs_every_migration_through_0096_and_ends_without_the_tables(tmp_path):
    db = tmp_path / "fresh.db"
    for _ in range(2):                                               # the first launch, then the next
        await _boot(db)
        assert not TABLES & _tables(db)
        assert "capability_sources" in _tables(db) and "task_workers" in _tables(db)
    assert _versions(db) == {vid for vid, _ in runner.MIGRATIONS}
    assert "0096" in _versions(db)


async def test_an_upgrade_from_0095_with_rows_in_both_tables_drops_them(tmp_path):
    db = tmp_path / "arslan.db"
    await _at_0095_with_methods(db)
    before = set((tmp_path / "backups").glob("*.zip"))
    await _boot(db)
    assert not TABLES & _tables(db)
    assert "0096" in _versions(db)
    taken = sorted(set((tmp_path / "backups").glob("*.zip")) - before)   # the rows survive in the backup
    assert len(taken) == 1
    with zipfile.ZipFile(taken[0]) as archive:
        archive.extract("arslan.db", tmp_path / "restored")
    with closing(sqlite3.connect(tmp_path / "restored" / "arslan.db")) as copy:
        assert copy.execute("SELECT key, current_revision FROM professional_methods ORDER BY key").fetchall() \
            == [("apple-growth", 1), ("product-design", 1), ("research", 2)]
    await _boot(db)                                                  # the next launch does not bring them back
    assert not TABLES & _tables(db)


def test_a_second_run_and_a_database_without_the_tables_are_left_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'b.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE keep_me (id INTEGER PRIMARY KEY)")
            m0096.upgrade_sync(conn)
            m0096.upgrade_sync(conn)
        with engine.connect() as conn:
            names = {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        engine.dispose()
    assert names == {"keep_me"}
