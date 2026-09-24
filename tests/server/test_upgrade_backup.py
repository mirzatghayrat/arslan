import hashlib
import json
import sqlite3
import zipfile

import pytest
import sqlalchemy as sa

from server.db.migrations import runner
from server.services import backup, upgrade_backup


@pytest.fixture
def old_database(tmp_path, monkeypatch):
    path = tmp_path / "arslan.db"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE schema_version(version TEXT PRIMARY KEY, applied_at TEXT);"
                         "INSERT INTO schema_version VALUES ('0006','old');"
                         "CREATE TABLE retained(value TEXT); INSERT INTO retained VALUES ('canary');")
    def migrate(conn):
        conn.execute(sa.text("CREATE TABLE added(value TEXT)"))
    monkeypatch.setattr(runner, "MIGRATIONS", [("0006", lambda conn: None), ("0007", migrate)])
    return path


def apply(path):
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as conn:
            return runner.apply_pending(conn)
    finally:
        engine.dispose()


def test_backup_before_migration_and_no_backup_when_current(old_database):
    assert apply(old_database) == ["0007"]
    archives = list((old_database.parent / "backups").glob("*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for name, entry in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == entry["sha256"]
        restored = old_database.parent / "snapshot.db"
        restored.write_bytes(archive.read("arslan.db"))
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT version FROM schema_version").fetchall() == [("0006",)]
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='added'").fetchall()
    assert apply(old_database) == []
    assert list((old_database.parent / "backups").glob("*.zip")) == archives


def test_backup_failure_prevents_migration_byte_for_byte(old_database, monkeypatch):
    before = old_database.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("private path must not escape")
    monkeypatch.setattr(backup, "create", fail)
    with pytest.raises(RuntimeError, match="^database_upgrade_backup_failed$"):
        apply(old_database)
    assert old_database.read_bytes() == before
    with sqlite3.connect(old_database) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='added'").fetchall()


def test_low_disk_refuses_before_backup(old_database, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(upgrade_backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    monkeypatch.setattr(backup, "create", lambda *a, **k: pytest.fail("not enough disk"))
    before = old_database.read_bytes()
    with pytest.raises(RuntimeError, match="^database_upgrade_backup_failed$"):
        apply(old_database)
    assert old_database.read_bytes() == before


def test_retains_three_automatic_archives_not_manual(old_database):
    directory = old_database.parent / "backups"
    directory.mkdir()
    manual = directory / "manual.zip"
    manual.write_bytes(b"retain")
    for index in range(5):
        upgrade_backup.create(old_database, f"000{index}", "0007")
    assert len(list(directory.glob("upgrade-*.zip"))) == 3
    assert manual.read_bytes() == b"retain"
