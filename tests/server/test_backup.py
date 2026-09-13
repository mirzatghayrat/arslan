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
