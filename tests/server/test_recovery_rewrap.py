import base64
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from server.crypto_material import keyring
from server.services import recovery_rewrap as rewrap
from server.services.recovery_preflight import check
from server.services.data_profile_lock import hold, activation_record_path

OLD = 'synthetic-backup-only'
NEW = 'synthetic-installation-only'
SALT = bytes(range(16))
NAMES = ['llm_api_key', 'search_api_key', 'github_token', '_ssh_identity_private',
         'mcp_oauth_tokens_1', 'mcp_oauth_client_1']


@pytest.fixture
def profiles(tmp_path):
    active, candidate = tmp_path / 'active', tmp_path / 'candidate'
    active.mkdir()
    candidate.mkdir()
    (active / 'arslan.db').write_bytes(b'original database must never change')
    with sqlite3.connect(candidate / 'arslan.db') as db:
        db.executescript('CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT);'
                         'CREATE TABLE provider_configs(id INTEGER PRIMARY KEY,api_key TEXT);'
                         'CREATE TABLE mcp_servers(id INTEGER PRIMARY KEY,env TEXT);')
        db.execute('INSERT INTO settings VALUES (?,?)', ('crypto_salt_b64', base64.b64encode(SALT).decode()))
        token = keyring(OLD, SALT).encrypt(b'synthetic-private-value').decode()
        db.executemany('INSERT INTO settings VALUES (?,?)', [(key, token) for key in NAMES])
        db.execute("INSERT INTO settings VALUES ('language','ja')")
        db.execute('INSERT INTO provider_configs VALUES (1,?)', (token,))
        db.execute('INSERT INTO mcp_servers VALUES (1,?)', (token,))
    return active, candidate


def assert_refused_unchanged(profiles, source=OLD, target=NEW):
    active, candidate = profiles
    before = (candidate / 'arslan.db').read_bytes()
    with pytest.raises(ValueError, match='^recovery_rewrap_refused$'):
        rewrap.rewrap_candidate(active, candidate, source, target)
    assert (candidate / 'arslan.db').read_bytes() == before
    assert (active / 'arslan.db').read_bytes() == b'original database must never change'
    assert not list(candidate.glob('.rewrap-*'))


@pytest.mark.parametrize('target', [NEW, OLD, '  ' + NEW + '\n'])
def test_all_sites_rewrapped_without_other_data_or_key_storage(profiles, target):
    active, candidate = profiles
    result = rewrap.rewrap_candidate(active, candidate, OLD, target)
    assert result == {'rewrapped': True, 'credentials': 8, 'secret_persisted': False}
    assert check(candidate / 'arslan.db', target)['status'] == 'compatible'
    if target.strip() != OLD:
        assert check(candidate / 'arslan.db', OLD)['unreadable'] == 8
    with sqlite3.connect(candidate / 'arslan.db') as db:
        assert db.execute("SELECT value FROM settings WHERE key='language'").fetchone()[0] == 'ja'
        assert db.execute("SELECT value FROM settings WHERE key='crypto_salt_b64'").fetchone()[0] == base64.b64encode(SALT).decode()
        for key in NAMES:
            token = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()[0]
            assert keyring(target.strip(), SALT).decrypt(token.encode()) == b'synthetic-private-value'
    assert (active / 'arslan.db').read_bytes() == b'original database must never change'
    assert not list(candidate.glob('.rewrap-*'))
    assert set(p.name for p in candidate.iterdir()) == {'arslan.db', '.arslan.db.arslan-lock'}
    assert OLD not in json.dumps(result) and NEW not in json.dumps(result)


@pytest.mark.parametrize('source,target', [('wrong', NEW), (OLD, ''), (None, NEW), (OLD, 'x\0y'), (OLD, 'x' * 8193)])
def test_wrong_or_invalid_secret_preserves_candidate(profiles, source, target):
    assert_refused_unchanged(profiles, source, target)


@pytest.mark.parametrize('change', ['mixed', 'corrupt', 'blob', 'salt', 'trigger', 'null_id', 'duplicate'])
def test_unreadable_or_ambiguous_database_is_not_partially_recovered(profiles, change):
    database = profiles[1] / 'arslan.db'
    with sqlite3.connect(database) as db:
        if change == 'mixed':
            db.execute('UPDATE mcp_servers SET env=?', (keyring(NEW, SALT).encrypt(b'other').decode(),))
        elif change == 'corrupt':
            db.execute("UPDATE mcp_servers SET env='broken'")
        elif change == 'blob':
            db.execute('UPDATE mcp_servers SET env=?', (b'binary',))
        elif change == 'salt':
            db.execute("UPDATE settings SET value='bad' WHERE key='crypto_salt_b64'")
        elif change == 'trigger':
            db.execute("CREATE TRIGGER hide_change AFTER UPDATE ON settings BEGIN DELETE FROM mcp_servers; END")
        else:
            db.execute('ALTER TABLE mcp_servers RENAME TO previous')
            db.execute('CREATE TABLE mcp_servers(id INTEGER,env TEXT)')
            db.execute('INSERT INTO mcp_servers SELECT id,env FROM previous')
            if change == 'null_id':
                db.execute('UPDATE mcp_servers SET id=NULL')
            else:
                db.execute('INSERT INTO mcp_servers SELECT * FROM previous')
    assert_refused_unchanged(profiles)


@pytest.mark.parametrize('limit', ['MAX_CREDENTIALS', 'MAX_TOKEN_BYTES', 'MAX_TOTAL_TOKENS'])
def test_limits_preserve_original_candidate(profiles, monkeypatch, limit):
    monkeypatch.setattr(rewrap, limit, 1)
    assert_refused_unchanged(profiles)


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_live_sqlite_sidecars_refuse(profiles, suffix):
    (profiles[1] / ('arslan.db' + suffix)).touch()
    assert_refused_unchanged(profiles)


def test_write_failure_after_staged_rewrite_never_installs(profiles, monkeypatch):
    rewrite = rewrap._rewrite
    def fail(db, source, target):
        rewrite(db, source, target)
        raise OSError('synthetic write failure')
    monkeypatch.setattr(rewrap, '_rewrite', fail)
    assert_refused_unchanged(profiles)


def test_replace_failure_preserves_candidate(profiles, monkeypatch):
    def fail(*_):
        raise OSError('synthetic replace failure')
    monkeypatch.setattr(rewrap.os, 'replace', fail)
    assert_refused_unchanged(profiles)


def test_active_profile_cannot_be_selected(profiles):
    with pytest.raises(ValueError, match='recovery_rewrap_refused'):
        rewrap.rewrap_candidate(profiles[0], profiles[0], OLD, NEW)
    assert (profiles[0] / 'arslan.db').read_bytes() == b'original database must never change'


def test_symlink_database_is_never_followed(profiles):
    active, candidate = profiles
    database = candidate / 'arslan.db'
    retained = candidate / 'retained.db'
    database.rename(retained)
    database.symlink_to(retained)
    assert_refused_unchanged(profiles)
    assert database.is_symlink()


def test_fresh_process_does_not_import_configuration_or_bootstrap_keys(profiles, tmp_path):
    home = tmp_path / 'empty-home'
    home.mkdir()
    code = ('import json,sys\nfrom pathlib import Path\n'
            'from server.services.recovery_rewrap import rewrap_candidate\n'
            'secrets=json.loads(sys.stdin.read())\n'
            'print(json.dumps(rewrap_candidate(Path(sys.argv[1]),Path(sys.argv[2]),*secrets)))\n'
            'assert "server.config" not in sys.modules and "server.crypto" not in sys.modules\n')
    result = subprocess.run([sys.executable, '-c', code, *(str(p) for p in profiles)],
                            input=json.dumps([OLD, NEW]), text=True, capture_output=True, timeout=15,
                            cwd=Path(__file__).resolve().parents[2], env={'PATH': os.environ['PATH'], 'HOME': str(home)})
    assert result.returncode == 0 and result.stderr == ''
    assert json.loads(result.stdout)['credentials'] == 8
    assert not list(home.iterdir())


def test_legacy_without_salt_remains_readable_by_normal_target_key(profiles):
    active, candidate = profiles
    token = keyring(OLD, None).encrypt(b'legacy-private').decode()
    with sqlite3.connect(candidate / 'arslan.db') as db:
        db.execute("DELETE FROM settings WHERE key='crypto_salt_b64'")
        db.executemany('UPDATE settings SET value=? WHERE key=?', [(token, name) for name in NAMES])
        db.execute('UPDATE provider_configs SET api_key=?', (token,))
        db.execute('UPDATE mcp_servers SET env=?', (token,))
    assert rewrap.rewrap_candidate(active, candidate, OLD, NEW)['credentials'] == 8
    assert check(candidate / 'arslan.db', NEW)['status'] == 'compatible'
    with sqlite3.connect(candidate / 'arslan.db') as db:
        assert db.execute("SELECT 1 FROM settings WHERE key='crypto_salt_b64'").fetchone() is None


def test_no_credentials_does_not_create_salt_or_secret(profiles):
    with sqlite3.connect(profiles[1] / 'arslan.db') as db:
        db.execute('DELETE FROM settings')
        db.execute('DELETE FROM provider_configs')
        db.execute('DELETE FROM mcp_servers')
    assert rewrap.rewrap_candidate(*profiles, OLD, NEW)['credentials'] == 0
    assert check(profiles[1] / 'arslan.db', None)['status'] == 'no_stored_credentials'


@pytest.mark.parametrize('index', [0, 1])
def test_busy_profile_is_not_modified(profiles, index):
    with hold(profiles[index] / 'arslan.db'):
        assert_refused_unchanged(profiles)


@pytest.mark.parametrize('index', [0, 1])
def test_pending_activation_is_not_modified(profiles, index):
    activation_record_path(profiles[index] / 'arslan.db').write_text('{}')
    assert_refused_unchanged(profiles)


def test_hardlinked_database_is_not_modified(profiles):
    os.link(profiles[1] / 'arslan.db', profiles[1] / 'other.db')
    assert_refused_unchanged(profiles)


def test_failed_target_readback_never_installs(profiles, monkeypatch):
    original = rewrap.keyring
    class BrokenTarget:
        def encrypt(self, _value):
            return original(NEW, SALT).encrypt(b'wrong-plaintext')
        def decrypt(self, value):
            return original(NEW, SALT).decrypt(value)
    monkeypatch.setattr(rewrap, 'keyring', lambda secret, salt: BrokenTarget() if secret == NEW else original(secret, salt))
    assert_refused_unchanged(profiles)


def test_concurrent_candidate_change_is_not_overwritten(profiles, monkeypatch):
    original = rewrap._rewrite
    database = profiles[1] / 'arslan.db'
    def change(db, source, target):
        result = original(db, source, target)
        with sqlite3.connect(database) as competing:
            competing.execute("UPDATE settings SET value='fr' WHERE key='language'")
        return result
    monkeypatch.setattr(rewrap, '_rewrite', change)
    with pytest.raises(ValueError, match='recovery_rewrap_refused'):
        rewrap.rewrap_candidate(*profiles, OLD, NEW)
    assert check(database, OLD)['status'] == 'compatible'
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT value FROM settings WHERE key='language'").fetchone()[0] == 'fr'
    assert not list(profiles[1].glob('.rewrap-*'))


def test_post_replace_sync_failure_is_not_reported_as_success(profiles, monkeypatch):
    original = rewrap.os.fsync
    calls = 0
    def fail_parent(fd):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError('synthetic parent sync failure')
        original(fd)
    monkeypatch.setattr(rewrap.os, 'fsync', fail_parent)
    with pytest.raises(ValueError, match='recovery_rewrap_refused'):
        rewrap.rewrap_candidate(*profiles, OLD, NEW)
    # The replacement occurred; the caller must treat refusal as uncertain,
    # never retry assuming the old key is still the candidate's key.
    assert check(profiles[1] / 'arslan.db', NEW)['status'] == 'compatible'
    assert (profiles[0] / 'arslan.db').read_bytes() == b'original database must never change'
    assert not list(profiles[1].glob('.rewrap-*'))
