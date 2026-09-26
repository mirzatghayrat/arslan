"""Check the acceptance launcher, not native UI or a packaged-app result."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[2] / "packaging/fresh_install_check.py"
    spec = importlib.util.spec_from_file_location("fresh_install_isolation_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("override", ["", "foreign"])
def test_boot_does_not_inherit_profile_or_execution_overrides(probe, tmp_path, monkeypatch, override):
    home = tmp_path / "isolated-home"
    foreign = tmp_path / "foreign-secret"
    foreign.write_text("synthetic-key-must-not-be-read", encoding="utf-8")
    poisoned = {
        "ARSLAN_SECRET_KEY_FILE": str(foreign) if override else "",
        "ARSLAN_SECRET_KEY": "synthetic-inherited-secret",
        "ARSLAN_DB_PATH": str(tmp_path / "foreign.db"),
        "ARSLAN_API_TOKEN": "synthetic-token",
        "ARSLAN_ENV": "prod",
        "ARSLAN_STATIC_DIR": str(tmp_path / "wrong-ui"),
        "ARSLAN_SANDBOX_PYTHON": "/must-not-run",
        "PYTHONPATH": "/must-not-import",
        "DYLD_INSERT_LIBRARIES": "/must-not-load",
        "OPENAI_API_KEY": "synthetic-provider-key",
        "HTTPS_PROXY": "http://synthetic.invalid:9999",
    }
    for name, value in poisoned.items():
        monkeypatch.setenv(name, value)
    captured = {}

    def spawn(argv, **kwargs):
        captured.update(kwargs)
        kwargs["stdout"].write(
            b"network: proxying through http://127.0.0.1:7899 (loopback exempt)\n"
            b"INFO:     Uvicorn running on http://127.0.0.1:54321 (Press CTRL+C to quit)\n"
        )
        kwargs["stdout"].flush()
        return SimpleNamespace(poll=lambda: None)

    class Healthy:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(probe.subprocess, "Popen", spawn)
    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *a, **kw: Healthy())
    _, port, _ = probe.boot(tmp_path / "fixture.app", home)
    captured["stdout"].close()
    env = captured["env"]
    inherited_names = sorted(set(poisoned).intersection(env))
    assert inherited_names == []
    assert env["HOME"] == str(home)
    assert env["ARSLAN_DATA_DIR"] == "data"  # Deliberate packaged-sanitizer probe.
    assert Path(env["TMPDIR"]).is_relative_to(home)
    assert Path(env["TMPDIR"]).is_dir()
    assert port == 54321
    assert all(os.environ[name] == value for name, value in poisoned.items())
    assert foreign.read_text(encoding="utf-8") == "synthetic-key-must-not-be-read"


@pytest.mark.parametrize("line,expected", [
    ("network: proxying through http://127.0.0.1:7899 (loopback exempt)", None),
    ('INFO: GET http://127.0.0.1:1234/health', None),
    ('ERROR: failed to open http://127.0.0.1:1234', None),
    ('INFO:     Uvicorn running on http://127.0.0.1:64066 (Press CTRL+C to quit)', 64066),
    ('[sidecar] INFO:     Uvicorn running on http://127.0.0.1:54321 (Press CTRL+C to quit)', 54321),
])
def test_probe_matches_listening_server_not_other_loopback_urls(probe, line, expected):
    match = probe.PORT_RE.search(line)
    assert (int(match.group(1)) if match else None) == expected


def test_clean_child_generates_its_own_key_under_isolated_home(probe, tmp_path, monkeypatch):
    home = tmp_path / "isolated-home"
    home.mkdir()
    foreign = tmp_path / "foreign-secret"
    foreign.write_text("synthetic-key-must-not-be-read", encoding="utf-8")
    monkeypatch.setenv("ARSLAN_SECRET_KEY_FILE", str(foreign))
    env = probe._boot_environment(home)
    # Real source bootstrap in a child interpreter, not a frozen bundle or GUI.
    script = """
import importlib.util, logging, pathlib, sys
foreign = sys.argv[1]
def deny_network(event, args):
    if event in {'socket.connect', 'socket.connect_ex', 'socket.getaddrinfo'}:
        raise RuntimeError('network forbidden in isolation test')
    if event == 'open' and args[0] == foreign:
        raise RuntimeError('foreign secret access forbidden')
sys.addaudithook(deny_network)
spec = importlib.util.spec_from_file_location('entry', 'packaging/server_entry.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
entry._sanitize_env()
from server.profile_paths import resolve_data_dir
from server.secret_bootstrap import bootstrap_secret_key
home = pathlib.Path.home()
suffix = 'Library/Application Support/Arslan' if sys.platform == 'darwin' else '.local/share/Arslan'
if sys.platform == 'win32':
    suffix = 'AppData/Roaming/Arslan'
assert resolve_data_dir() == home / suffix
key = bootstrap_secret_key(env='dev', explicit='', data_dir=resolve_data_dir(), log=logging.getLogger())
assert key and (home / '.arslan/secret_key').read_text().strip() == key
print('isolated-key-created')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(foreign)], cwd=probe.REPO, env=env,
        text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated-key-created"
    assert foreign.read_text(encoding="utf-8") == "synthetic-key-must-not-be-read"
