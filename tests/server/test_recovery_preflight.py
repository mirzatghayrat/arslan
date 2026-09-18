import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from cryptography.fernet import Fernet
import pytest

from server import config, crypto
from server.services import recovery_preflight, crypto_boot

SECRET = "synthetic-preflight-secret-only"
PLAINTEXT = "synthetic-private-credential"
SALT = bytes(range(16))
SETTINGS = ["llm_api_key", "search_api_key", "github_token", "_ssh_identity_private",
            "mcp_oauth_tokens_1", "mcp_oauth_client_1"]


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "settings", replace(config.settings, secret_key=SECRET))
    monkeypatch.setattr(crypto, "_salt", SALT)
    monkeypatch.setattr(crypto, "_salt_source", "synthetic-preflight")
    database = tmp_path / "restored.db"
    with sqlite3.connect(database) as db:
        db.executescript("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);"
                         "CREATE TABLE provider_configs (id INTEGER, api_key TEXT);"
                         "CREATE TABLE mcp_servers (id INTEGER, env TEXT);")
        token = crypto.encrypt(PLAINTEXT)
        db.execute("INSERT INTO settings VALUES ('crypto_salt_b64', ?)", (base64.b64encode(SALT).decode(),))
        db.executemany("INSERT INTO settings VALUES (?, ?)", [(name, token) for name in SETTINGS])
        db.execute("INSERT INTO settings VALUES ('_ssh_identity_public', 'public plaintext')")
        db.execute("INSERT INTO settings VALUES ('language', 'zh')")
        db.execute("INSERT INTO provider_configs VALUES (1, ?)", (token,))
        db.execute("INSERT INTO mcp_servers VALUES (1, ?)", (token,))
    return database


@pytest.mark.parametrize("secret,status,unreadable", [(SECRET, "compatible", 0),
    ("wrong-synthetic-secret", "unreadable_credentials", 8), (None, "secret_required", 0)])
def test_all_credential_sites_are_checked_without_writes_or_disclosure(database, secret, status, unreadable):
    before = database.read_bytes()
    names = set(database.parent.iterdir())
    salt_before = crypto.current_salt()
    result = recovery_preflight.check(database, secret)
    assert result == {"status": status, "checked": 8, "unreadable": unreadable}
    encoded = json.dumps(result)
    assert SECRET not in encoded and PLAINTEXT not in encoded
    assert not any(name in encoded for name in SETTINGS)
    assert database.read_bytes() == before and set(database.parent.iterdir()) == names
    assert crypto.current_salt() == salt_before


@pytest.mark.parametrize("key", SETTINGS)
def test_one_unreadable_setting_blocks_compatibility(database, key):
    with sqlite3.connect(database) as db:
        db.execute("UPDATE settings SET value='not-a-valid-ciphertext' WHERE key=?", (key,))
    assert recovery_preflight.check(database, SECRET) == {
        "status": "unreadable_credentials", "checked": 8, "unreadable": 1}


@pytest.mark.parametrize("value", ["not-base64!", "eA==", "x" * 4097])
def test_corrupt_salt_never_replaced(database, value):
    with sqlite3.connect(database) as db:
        db.execute("UPDATE settings SET value=? WHERE key='crypto_salt_b64'", (value,))
    before = database.read_bytes()
    assert recovery_preflight.check(database, SECRET)["status"] == "invalid_salt"
    assert database.read_bytes() == before


def test_legacy_without_salt_is_readable_but_primary_without_salt_is_not(database):
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM settings WHERE key='crypto_salt_b64'")
    assert recovery_preflight.check(database, SECRET)["status"] == "unreadable_credentials"
    legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET.encode()).digest()))
    token = legacy.encrypt(PLAINTEXT.encode()).decode()
    with sqlite3.connect(database) as db:
        db.executemany("UPDATE settings SET value=? WHERE key=?", [(token, name) for name in SETTINGS])
        db.execute("UPDATE provider_configs SET api_key=?", (token,))
        db.execute("UPDATE mcp_servers SET env=?", (token,))
    assert recovery_preflight.check(database, SECRET)["status"] == "compatible"


def test_empty_database_does_not_require_or_invent_a_secret(tmp_path):
    database = tmp_path / "empty.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    assert recovery_preflight.check(database, None) == {
        "status": "no_stored_credentials", "checked": 0, "unreadable": 0}


def test_limits_and_nonregular_input_fail_closed(database, tmp_path, monkeypatch):
    monkeypatch.setattr(recovery_preflight, "MAX_CREDENTIALS", 2)
    assert recovery_preflight.check(database, SECRET)["status"] == "credential_limit"
    link = tmp_path / "link.db"
    link.symlink_to(database)
    assert recovery_preflight.check(link, SECRET)["status"] == "preflight_unavailable"
    missing = tmp_path / "missing.db"
    assert recovery_preflight.check(missing, SECRET)["status"] == "preflight_unavailable"
    assert not missing.exists()


def test_import_and_check_do_not_bootstrap_config_or_home(database, tmp_path):
    home = tmp_path / "empty-home"
    home.mkdir()
    code = ("import json, sys\nfrom pathlib import Path\n"
            "from server.services.recovery_preflight import check\n"
            "result = check(Path(sys.argv[1]), sys.stdin.read())\n"
            "assert 'server.config' not in sys.modules and 'server.crypto' not in sys.modules\n"
            "print(json.dumps(result))\n")
    run = subprocess.run([sys.executable, "-c", code, str(database)], input=SECRET, text=True,
                         cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=10,
                         env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)})
    assert run.returncode == 0 and not run.stderr
    assert json.loads(run.stdout) == {"status": "compatible", "checked": 8, "unreadable": 0}
    assert not list(home.iterdir())


def test_boot_inventory_also_includes_oauth_and_ssh(database):
    with sqlite3.connect(database) as db:
        class Connection:
            def exec_driver_sql(self, sql, parameters=()):
                return db.execute(sql, parameters)
        found = list(crypto_boot._stored_ciphertext(Connection()))
    assert len(found) == 8
    assert {row[1] for row in found if row[0] == "settings"} == set(SETTINGS)


def test_new_inventory_preserves_legacy_migration_and_skips_empty_oauth(database):
    legacy = crypto.legacy_fernet().encrypt(PLAINTEXT.encode()).decode()
    with sqlite3.connect(database) as db:
        db.executemany("UPDATE settings SET value=? WHERE key=?", [(legacy, name) for name in SETTINGS])
        db.execute("INSERT INTO settings VALUES ('mcp_oauth_tokens_empty', '')")
        db.execute("INSERT INTO settings VALUES ('mcp_oauth_client_null', NULL)")
        db.execute("UPDATE provider_configs SET api_key=?", (legacy,))
        db.execute("UPDATE mcp_servers SET env=?", (legacy,))
        class Connection:
            def exec_driver_sql(self, sql, parameters=()):
                return db.execute(sql, parameters)
        connection = Connection()
        assert crypto_boot.migrate_legacy_ciphertext(connection) == 8
        assert crypto_boot.migrate_legacy_ciphertext(connection) == 0
        for _, _, token in crypto_boot._stored_ciphertext(connection):
            assert crypto.primary_fernet().decrypt(token.encode()).decode() == PLAINTEXT
    assert recovery_preflight.check(database, SECRET)["status"] == "compatible"


@pytest.mark.parametrize("mode", ["oversized", "blob", "utf8"])
def test_malformed_credential_is_not_compatible(database, monkeypatch, mode):
    if mode == "oversized":
        monkeypatch.setattr(recovery_preflight, "MAX_TOKEN_BYTES", 4)
    else:
        token = b"blob" if mode == "blob" else crypto.primary_fernet().encrypt(b"\xff").decode()
        with sqlite3.connect(database) as db:
            db.execute("UPDATE provider_configs SET api_key=?", (token,))
    assert recovery_preflight.check(database, SECRET)["status"] == "unreadable_credentials"


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_pending_journal_refuses_without_ignoring_uncheckpointed_data(database, suffix):
    sidecar = database.with_name(database.name + suffix)
    sidecar.write_bytes(b"synthetic pending journal")
    before = database.read_bytes()
    assert recovery_preflight.check(database, SECRET)["status"] == "preflight_unavailable"
    assert database.read_bytes() == before
    assert sidecar.read_bytes() == b"synthetic pending journal"


def test_checkpointed_wal_snapshot_does_not_create_sidecars(database, monkeypatch):
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    db.close()
    before = set(database.parent.iterdir())
    original_check = recovery_preflight._check
    def observed(connection, secret):
        result = original_check(connection, secret)
        assert set(database.parent.iterdir()) == before  # Also while SQLite is open.
        return result
    monkeypatch.setattr(recovery_preflight, "_check", observed)
    assert recovery_preflight.check(database, SECRET)["status"] == "compatible"
    assert set(database.parent.iterdir()) == before
