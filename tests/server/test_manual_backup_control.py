"""Actual maintenance subprocess, isolated synthetic HOME, never a provider."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

import pytest
from server.services.data_profile_lock import hold


@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS profile path")
def test_manual_backup_stopped_profile_exclusive_no_secret_bootstrap(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    profile = home / "Library/Application Support/Arslan"
    profile.mkdir(parents=True)
    database = profile / "arslan.db"
    with sqlite3.connect(database) as db:
        db.executescript("CREATE TABLE retained(value TEXT); INSERT INTO retained VALUES ('synthetic-only')")
    before = database.read_bytes()
    name = "manual-" + "a" * 64 + ".zip"
    def invoke():
        return subprocess.run([sys.executable, str(root / "packaging/server_entry.py"), "--activation-control"],
            cwd=root, env={"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                           "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1",
                           "ARSLAN_DATA_DIR": str(tmp_path / "must-not-use"),
                           "ARSLAN_DB_PATH": str(tmp_path / "must-not-use" / "wrong.db")},
            input=json.dumps({"action": "backup", "name": name}) + "\n", text=True,
            capture_output=True, timeout=15)
    with hold(database):
        assert invoke().returncode == 1
    result = invoke()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"]["secret_included"] is False
    archive = profile / "backups" / name
    original_archive = archive.read_bytes()
    with zipfile.ZipFile(archive) as packed:
        assert set(packed.namelist()) == {"arslan.db", "manifest.json"}
    assert invoke().returncode == 1  # Never overwrite.
    assert archive.read_bytes() == original_archive
    assert database.read_bytes() == before
    assert not (home / ".arslan").exists()
    assert not (profile / "api_token").exists()
    assert not (tmp_path / "must-not-use").exists()
