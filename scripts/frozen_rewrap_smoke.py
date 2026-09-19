"""Synthetic native rewrap/trial/finalize with two default-key normal boots."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from scripts.frozen_sidecar_smoke import start, stop
from server.crypto_material import keyring
from server.services import backup
from server.services.data_profile_lock import activation_record_path
from server.services.recovery_preflight import check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('native_test', type=Path)
    args = parser.parse_args()
    binary, native = args.binary.resolve(), args.native_test.resolve()
    for path in (binary, native):
        assert path.is_file() and path.is_relative_to(Path(tempfile.gettempdir()).resolve())
        assert any(p.startswith(('arslan-native-candidate.', 'arslan-candidate-build.')) for p in path.parts)
    assert binary.name == 'arslan-server' and native.name.startswith('arslan_desktop_lib-')
    old, target, credential = 'frozen-smoke-synthetic-only', 'frozen-smoke-target-only', 'synthetic-provider-value'
    with tempfile.TemporaryDirectory(prefix='arslan-frozen-trial-') as folder:
        home = Path(folder)
        process, client, _ = start(binary, home)
        try:
            assert client.put('/api/v1/settings', json={'llm_api_key': credential}).status_code == 200
        finally:
            client.close()
            assert stop(process) == 0
        active = home / 'Library/Application Support/Arslan'
        archive = home / 'backup.zip'
        backup.create(active, archive)
        archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        # Fixture setup: the installation now uses another durable key, while
        # the historical backup still uses the original backup key.
        with sqlite3.connect(active / 'arslan.db') as db:
            salt = base64.b64decode(db.execute("SELECT value FROM settings WHERE key='crypto_salt_b64'").fetchone()[0])
            db.execute("UPDATE settings SET value=? WHERE key='llm_api_key'",
                       (keyring(target, salt).encrypt(credential.encode()).decode(),))
        db.close()
        original = (active / 'arslan.db').read_bytes()
        key_file = home / '.arslan/secret_key'
        key_file.parent.mkdir(mode=0o700)
        key_file.write_text(target)
        key_file.chmod(0o600)

        def control(action, operation='', target_key=False):
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'TMPDIR': str(home), 'ARSLAN_LIVE_LLM': '0',
                   'ARSLAN_CONTROL_TEST_BINARY': str(binary), 'ARSLAN_CONTROL_TEST_ACTION': action,
                   'ARSLAN_CONTROL_TEST_OPERATION': operation, 'ARSLAN_SECRET_KEY': 'wrong-inherited-secret'}
            if target_key:
                env['ARSLAN_CONTROL_TEST_TARGET_KEY'] = '1'
            result = subprocess.run([str(native), 'recovery_control::tests::packaged_control_fixture',
                                     '--ignored', '--exact', '--nocapture'], cwd=home, env=env,
                                    capture_output=True, timeout=110 if action == 'trial' else 35)
            assert result.returncode == 0, 'native fixture failed'
            assert all(value.encode() not in result.stdout + result.stderr for value in (old, target, credential))
            lines = [line.split(b'NATIVE_CONTROL_RESULT=', 1)[1] for line in result.stdout.splitlines()
                     if b'NATIVE_CONTROL_RESULT=' in line]
            assert len(lines) == 1
            message = json.loads(lines[0])
            assert message['ok'] is True
            return message['result']

        assert control('prepare')['prepared']
        candidate = active.with_name('restored')
        assert check(candidate / 'arslan.db', old)['status'] == 'compatible'
        assert control('rewrap') == {'rewrapped': True, 'candidate': 'restored',
                                     'credentials': 1, 'secret_persisted': False}
        assert check(candidate / 'arslan.db', target)['status'] == 'compatible'
        assert check(candidate / 'arslan.db', old)['status'] == 'unreadable_credentials'
        assert (active / 'arslan.db').read_bytes() == original
        operation = control('switch', target_key=True)['operation_id']
        record = json.loads(activation_record_path(active / 'arslan.db').read_bytes())
        assert control('trial', operation, True)['trial_completed']
        assert control('finalize', operation, True)['finalized']
        for _ in range(2):
            process, client, _ = start(binary, home, secret=None)
            try:
                settings = client.get('/api/v1/settings').json()
                assert settings['llm_api_key'] == 'sy...alue'
            finally:
                client.close()
                assert stop(process) == 0
            assert key_file.read_text() == target and key_file.stat().st_mode & 0o777 == 0o600
        assert (active.parent / record['previous'] / 'arslan.db').read_bytes() == original
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == archive_hash
        print(json.dumps({'frozen_native_rewrap': 'passed', 'two_normal_default_key_boots': True,
                          'original_and_archive_retained': True, 'external_key_unchanged': True,
                          'native_ui': False, 'real_model': False, 'installed_app': False,
                          'backend_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
