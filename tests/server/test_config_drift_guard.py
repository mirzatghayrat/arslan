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

from tests.server.conftest import _heal_config_drift


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
