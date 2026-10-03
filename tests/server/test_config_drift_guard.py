"""S4.2-d M8 — the conftest config-drift guard heals api_token pollution.

Root cause of the flaky test_brain_open_when_token_unset: a fixture (e.g.
test_usage_api's client) reloads server.config with ARSLAN_API_TOKEN set;
monkeypatch restores the ENV afterwards but nothing restored the MODULE, so
config.settings.api_token leaked into every later test. Ordering cannot be
asserted reliably under pytest-randomly, so this drives the healing function
directly.
"""
import importlib
import os

import pytest

from tests.server.conftest import _heal_config_drift, _restore_config


def test_guard_heals_api_token_drift(monkeypatch):
    import server.config as config

    ambient = os.environ.get("ARSLAN_API_TOKEN", "") or ""
    assert (config.settings.api_token or "") == ambient  # pre-assert: clean start

    # Simulate the polluter: reload config under a mutated env…
    monkeypatch.setenv("ARSLAN_API_TOKEN", "polluted-token")
    importlib.reload(config)
    assert config.settings.api_token == "polluted-token"  # ⓪ pollution took effect

    # …then the env is restored (what monkeypatch teardown does) but the module
    # is not. The guard must detect the drift and reload.
    monkeypatch.delenv("ARSLAN_API_TOKEN", raising=False)
    if ambient:
        monkeypatch.setenv("ARSLAN_API_TOKEN", ambient)
    assert _heal_config_drift() is True
    assert (config.settings.api_token or "") == ambient


def test_guard_is_a_noop_without_drift():
    assert _heal_config_drift() is False


def _paths(config):
    return config.settings.data_dir, config.settings.db_path, config.settings.spawns_dir


@pytest.mark.parametrize("key", ["ARSLAN_DATA_DIR", "ARSLAN_SPAWNS_DIR", "ARSLAN_DB_PATH"])
def test_guard_heals_path_drift(monkeypatch, tmp_path, key):
    """2026-10-03: test_data_dir's teardown left config pointing at the platform data
    dir; nothing compared paths, so a later dispatch mkdir'd ``spawns/S/.evolution``
    there. A reload under a patched path env must be healed like the token is."""
    import server.config as config

    ambient = _paths(config)
    monkeypatch.setenv(key, str(tmp_path / "polluted"))
    importlib.reload(config)
    assert _paths(config) != ambient  # ⓪ pollution took effect

    monkeypatch.undo()  # the env comes back; the module does not
    assert _heal_config_drift() is True
    assert _paths(config) == ambient


def test_restore_puts_the_env_back_before_healing(tmp_path):
    """The heal compares config with the env, so the env must already be restored —
    otherwise it compares the polluted config with the polluting env and sees no drift.
    That ordering used to rest on which fixture instantiated monkeypatch first."""
    import server.config as config

    ambient = _paths(config)
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "polluted"))
        importlib.reload(config)
        assert _restore_config(mp) == []
        assert _paths(config) == ambient
    finally:
        mp.undo()


def test_restore_reports_config_left_inside_the_real_data_dir(tmp_path):
    import server.config as config

    ambient = _paths(config)
    real = tmp_path / "Arslan"  # stands in for the user's dir; nothing is created
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("ARSLAN_DATA_DIR", str(real / "does_not_exist_probe"))
        importlib.reload(config)
        leaked = _restore_config(mp, real_data_dir=real.resolve())
        assert len(leaked) == 3 and all("does_not_exist_probe" in path for path in leaked)
        assert _paths(config) == ambient  # healed as well as reported
        assert not real.exists()
    finally:
        mp.undo()
