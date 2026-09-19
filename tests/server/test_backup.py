import base64
import json
import sqlite3
import zipfile

import pytest

from server import crypto
from server.services import backup


def source(tmp_path):
    data = tmp_path / "source"
    data.mkdir()
    with sqlite3.connect(data / "arslan.db") as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO settings VALUES (?, ?)",
                   ("crypto_salt_b64", base64.b64encode(crypto.current_salt()).decode()))
        db.execute("INSERT INTO settings VALUES (?, ?)", ("credential", crypto.encrypt("synthetic-key")))
    db.close()
    (data / "artifacts").mkdir()
    (data / "artifacts" / "result.csv").write_text("answer\n42\n")
    (data / "api_token").write_text("never-include")
    return data


def test_backup_restore_preserves_salt_ciphertext_and_artifacts(tmp_path):
    data = source(tmp_path)
    archive = tmp_path / "backup.zip"
    result = backup.create(data, archive)
    assert not result["secret_included"]
    restored = tmp_path / "restored"
    backup.restore(archive, restored)
    assert not (restored / "api_token").exists()
    assert (restored / "artifacts/result.csv").read_text() == "answer\n42\n"
    with sqlite3.connect(restored / "arslan.db") as db:
        settings = dict(db.execute("SELECT key, value FROM settings"))
    crypto.adopt_salt(base64.b64decode(settings["crypto_salt_b64"]), source="restored-test-db")
    assert crypto.decrypt(settings["credential"]) == "synthetic-key"


@pytest.mark.parametrize("saved,expected", [(code, code) for code in ("en", "zh", "ja", "es", "de", "fr")]
                         + [("Chinese (Simplified)", "zh"), ("ja-JP", "ja"), (None, "en"),
                            ("xx", "en"), ("fr<script>", "en"), ("ja" * 100, "en"), (b"fr", "en")])
def test_restored_language_hint_is_derived_without_changing_backup_or_source(tmp_path, saved, expected):
    data = source(tmp_path)
    with sqlite3.connect(data / "arslan.db") as db:
        if saved is not None:
            db.execute("INSERT INTO settings VALUES ('language', ?)", (saved,))
    db.close()
    (data / "ui_language").write_text("de\n")  # stale cache is never authoritative
    archive = tmp_path / "locale.zip"
    backup.create(data, archive)
    original, archived = (data / "arslan.db").read_bytes(), archive.read_bytes()
    destination = tmp_path / "restored"
    result = backup.restore(archive, destination)
    assert result["files"] == 2  # archive members, excluding derived cache
    assert (destination / "ui_language").read_text() == expected + "\n"
    assert (destination / "ui_language").stat().st_mode & 0o777 == 0o600
    assert (data / "ui_language").read_text() == "de\n"
    assert (data / "arslan.db").read_bytes() == original
    assert archive.read_bytes() == archived
    with zipfile.ZipFile(archive) as packed:
        assert "ui_language" not in packed.namelist()


def test_hint_write_failure_does_not_install_candidate(tmp_path, monkeypatch):
    data = source(tmp_path)
    archive = tmp_path / "locale.zip"
    backup.create(data, archive)
    def refused(_stage):
        raise OSError("synthetic hint failure")
    monkeypatch.setattr(backup, "_restore_language_hint", refused)
    destination = tmp_path / "restored"
    with pytest.raises(OSError, match="synthetic hint failure"):
        backup.restore(archive, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".arslan-restore-*"))


@pytest.mark.parametrize("schema", ["missing", "view", "duplicates", "wrong-columns"])
def test_legacy_or_ambiguous_hint_schema_falls_back_without_database_writes(tmp_path, schema):
    staged = tmp_path / "stage"
    staged.mkdir()
    database = staged / "arslan.db"
    with sqlite3.connect(database) as db:
        if schema == "view":
            db.execute("CREATE VIEW settings AS SELECT 'language' AS key, 'fr' AS value")
        elif schema == "duplicates":
            db.execute("CREATE TABLE settings (key TEXT, value TEXT)")
            db.executemany("INSERT INTO settings VALUES ('language', ?)", [("fr",), ("ja",)])
        elif schema == "wrong-columns":
            db.execute("CREATE TABLE settings (unrelated TEXT)")
    db.close()
    original = database.read_bytes()
    backup._restore_language_hint(staged)
    assert (staged / "ui_language").read_text() == "en\n"
    assert database.read_bytes() == original


def test_restored_hint_does_not_bootstrap_keys_or_configuration(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    staged = tmp_path / "stage"
    staged.mkdir()
    with sqlite3.connect(staged / "arslan.db") as db:
        db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO settings VALUES ('language', 'ja')")
    code = ("import sys\nfrom pathlib import Path\n"
            "from server.services.backup import _restore_language_hint\n"
            "_restore_language_hint(Path(sys.argv[1]))\n"
            "assert 'server.config' not in sys.modules\n"
            "assert 'server.crypto' not in sys.modules\n")
    result = subprocess.run([sys.executable, "-c", code, str(staged)],
                            cwd=Path(__file__).resolve().parents[2], timeout=10,
                            capture_output=True,
                            env={"HOME": str(tmp_path), "PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    assert result.returncode == 0, result.stderr
    assert (staged / "ui_language").read_text() == "ja\n"
    assert not (tmp_path / ".arslan").exists()


def test_refuses_overwrite_and_symlink_assets(tmp_path):
    data = source(tmp_path)
    archive = tmp_path / "backup.zip"
    backup.create(data, archive)
    with pytest.raises(ValueError, match="already exists"):
        backup.create(data, archive)
    with pytest.raises(ValueError, match="NEW directory"):
        backup.restore(archive, data)
    (data / "artifacts/link").symlink_to(data / "api_token")
    with pytest.raises(ValueError, match="symlink"):
        backup.create(data, tmp_path / "other.zip")


def test_snapshot_includes_committed_wal_while_writer_remains_open(tmp_path):
    data = source(tmp_path)
    archive = tmp_path / "wal.zip"
    with sqlite3.connect(data / "arslan.db") as writer:
        writer.execute("INSERT INTO settings VALUES ('wal-only', 'committed')")
        writer.commit()
        assert (data / "arslan.db-wal").exists()
        backup.create(data, archive)
    restored = tmp_path / "wal-restored"
    backup.restore(archive, restored)
    with sqlite3.connect(restored / "arslan.db") as db:
        assert db.execute("SELECT value FROM settings WHERE key='wal-only'").fetchone() == ("committed",)


def test_restore_closes_integrity_connections_without_waiting_for_garbage_collection(tmp_path, monkeypatch):
    import gc
    from server.services.recovery_preflight import check

    data = source(tmp_path)
    archive = tmp_path / "closed.zip"
    backup.create(data, archive)
    target = tmp_path / "restored-closed"
    # Retain references so implicit refcount/GC cleanup cannot make this pass.
    original_connect = sqlite3.connect
    connections = []
    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection
    monkeypatch.setattr(backup.sqlite3, "connect", connect)
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        backup.create(data, tmp_path / "another-closed.zip")
        backup.restore(archive, target)
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
                connection.execute("SELECT 1")
        assert not list(target.glob("arslan.db-*"))
        assert check(target / "arslan.db", None)["status"] != "preflight_unavailable"
    finally:
        if was_enabled:
            gc.enable()


def test_restore_never_replaces_directory_created_after_final_check(tmp_path, monkeypatch):
    from pathlib import Path

    data = source(tmp_path)
    archive = tmp_path / "backup.zip"
    backup.create(data, archive)
    original_archive = archive.read_bytes()
    target = tmp_path / "target"
    original_exists = Path.exists
    checks = 0
    created_inode = None

    def race_after_check(path):
        nonlocal checks, created_inode
        result = original_exists(path)
        if path == target and not result:
            checks += 1
            if checks == 2:
                target.mkdir()
                created_inode = target.stat().st_ino
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Path, "exists", race_after_check)
        with pytest.raises(ValueError, match="restore destination appeared"):
            backup.restore(archive, target)
    assert created_inode is not None
    assert target.stat().st_ino == created_inode
    assert list(target.iterdir()) == []
    assert archive.read_bytes() == original_archive
    assert not list(tmp_path.glob(".arslan-restore-*"))
    target.rmdir()
    backup.restore(archive, target)
    assert (target / "artifacts/result.csv").read_text() == "answer\n42\n"


def test_install_refusal_cleans_staging_and_allows_explicit_retry(tmp_path, monkeypatch):
    import errno
    from server.services import atomic_install

    data = source(tmp_path)
    archive, target = tmp_path / "backup.zip", tmp_path / "target"
    backup.create(data, archive)
    before = archive.read_bytes()

    def refuse(*args):
        raise OSError(errno.ENOTSUP, "synthetic unsupported filesystem")

    with monkeypatch.context() as patch:
        patch.setattr(atomic_install, "install_directory", refuse)
        with pytest.raises(OSError, match="unsupported filesystem"):
            backup.restore(archive, target)
    assert archive.read_bytes() == before
    assert not target.exists()
    assert not list(tmp_path.glob(".arslan-restore-*"))
    backup.restore(archive, target)
    assert (target / "arslan.db").is_file()


@pytest.mark.parametrize("mutation", ["checksum", "traversal", "symlink", "extra", "duplicate"])
def test_corrupt_or_unsafe_archive_never_installs(tmp_path, mutation):
    data = source(tmp_path)
    clean, bad = tmp_path / "clean.zip", tmp_path / "bad.zip"
    backup.create(data, clean)
    with zipfile.ZipFile(clean) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    manifest = json.loads(entries["manifest.json"])
    if mutation == "checksum":
        entries["artifacts/result.csv"] = b"tampered"
    elif mutation == "traversal":
        entries["../escape"] = b"escape"
        manifest["files"]["../escape"] = {"bytes": 6, "sha256": backup._digest(b"escape")}
    elif mutation == "extra":
        entries["extra"] = b"extra"
    entries["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(bad, "w") as z:
        for name, contents in entries.items():
            info = zipfile.ZipInfo(name)
            if mutation == "symlink" and name == "artifacts/result.csv":
                info.external_attr = 0o120777 << 16
            z.writestr(info, contents)
        if mutation == "duplicate":
            with pytest.warns(UserWarning):
                z.writestr("arslan.db", entries["arslan.db"])
    target = tmp_path / "target"
    with pytest.raises(ValueError):
        backup.restore(bad, target)
    assert not target.exists() and not (tmp_path / "escape").exists()
