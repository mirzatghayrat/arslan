"""0100 (v0.1.64 SUB7): the `task_workers` table goes.

SUB6 deleted the helpers and the table's model; 0052 still creates the table from its own definition, so a
new install creates it there and 0100 drops it in the same boot. An install that kept helper rows loses the
table on its next boot, after the upgrade backup.

Booted the way the app boots (storage_boot.initialize on build_engine).
"""
from __future__ import annotations

import sqlite3
import zipfile
from contextlib import closing

import sqlalchemy as sa

from server.db.migrations import runner
from server.db.migrations.versions import _0052_task_workers as m0052
from server.db.migrations.versions import _0100_drop_task_workers as m0100
from server.db.session import build_engine
from server.services import storage_boot

INDEX = "ix_task_workers_task_id"


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


def _indexes(db_path) -> set[str]:
    return {name for (name,) in _rows(db_path, "SELECT name FROM sqlite_master WHERE type='index'")}


def _versions(db_path) -> set[str]:
    return {version for (version,) in _rows(db_path, "SELECT version FROM schema_version")}


async def _before_0100_with_a_helper_row(db_path) -> None:
    """An install from before SUB7: every other migration recorded, 0100 not, and one helper row stored."""
    await _boot(db_path)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")            # no task or attempt is made
            for statement in m0052._TASK_WORKERS:                     # the table as 0052 made it
                conn.exec_driver_sql(statement)
            conn.exec_driver_sql(
                "INSERT INTO task_workers (id, task_id, attempt_id, spec_revision, method_key, method_revision, "
                "fingerprint, brief, status, progress, created_at) VALUES ('w1', 't1', 'a1', 1, 'research', 2, "
                "'f', '{}', 'completed', '{}', '2026-10-27 09:00:00')")
            conn.exec_driver_sql("DELETE FROM schema_version WHERE version = '0100'")
    finally:
        engine.dispose()
    assert "task_workers" in _tables(db_path) and INDEX in _indexes(db_path)
    assert _versions(db_path) == {vid for vid, _ in runner.MIGRATIONS} - {"0100"}


def test_0100_is_in_the_boot_chain():
    ids = [vid for vid, _ in runner.MIGRATIONS]
    assert ids == sorted(ids)
    assert ("0100", m0100.upgrade_sync) in runner.MIGRATIONS


async def test_an_upgraded_install_with_a_helper_row_loses_the_table_after_a_backup(tmp_path):
    db = tmp_path / "arslan.db"
    await _before_0100_with_a_helper_row(db)
    before = set((tmp_path / "backups").glob("*.zip"))
    await _boot(db)
    assert "task_workers" not in _tables(db) and INDEX not in _indexes(db)
    assert "0100" in _versions(db)
    taken = sorted(set((tmp_path / "backups").glob("*.zip")) - before)   # the row survives in the backup
    assert len(taken) == 1
    with zipfile.ZipFile(taken[0]) as archive:
        archive.extract("arslan.db", tmp_path / "restored")
    with closing(sqlite3.connect(tmp_path / "restored" / "arslan.db")) as copy:
        assert copy.execute("SELECT id, status FROM task_workers").fetchall() == [("w1", "completed")]
    await _boot(db)                                                  # the next launch does not bring it back
    assert "task_workers" not in _tables(db)


async def test_a_new_install_ends_without_task_workers(tmp_path):
    db = tmp_path / "fresh.db"
    for _ in range(2):                                               # the first launch, then the next
        await _boot(db)
        assert "task_workers" not in _tables(db) and INDEX not in _indexes(db)
        assert "capability_sources" in _tables(db)
    assert _versions(db) == {vid for vid, _ in runner.MIGRATIONS}


def test_a_second_run_and_a_database_without_the_table_are_left_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'b.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE keep_me (id INTEGER PRIMARY KEY)")
            m0100.upgrade_sync(conn)
            m0100.upgrade_sync(conn)
        with engine.connect() as conn:
            names = {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        engine.dispose()
    assert names == {"keep_me"}
