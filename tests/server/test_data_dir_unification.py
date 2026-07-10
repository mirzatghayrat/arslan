"""S1 OSS-safety FIX 1: every subsystem must resolve its base dir from the ONE
resolved data-dir root, never from an independent ``os.environ.get("ARSLAN_DATA_DIR",
"data")`` default.

The bug: ``server.config`` defaults an UNSET ``ARSLAN_DATA_DIR`` to a per-platform
app-data dir (so the SQLite "brain" is stable across launch dirs), but several
subsystems still re-read the env with a CWD-relative ``"data"`` default. When
``ARSLAN_DATA_DIR`` is unset (e.g. Docker prod sets ``ARSLAN_ENV=prod`` but NOT
``ARSLAN_DATA_DIR``) the brain lands in the platform dir while skill_scripts /
artifacts / sandbox_env / the shell workspace land in CWD/``data`` — a silent split.

Fix: all subsystems resolve through ``config.data_dir()`` — the SAME resolver
``load_settings`` uses for ``settings.data_dir`` (no divergent ``"data"`` default).
This suite pins: (1) UNSET -> every subsystem root is under ``settings.data_dir``
(the platform dir), never CWD/data; (2) ``ARSLAN_DATA_DIR=data`` (the dev flow) ->
every subsystem still resolves to CWD/data (unchanged).

Each test reloads ``server.config`` under a monkeypatched env/platform (same harness
as test_data_dir) and the autouse fixture reloads config back to the ambient baseline
so the mutated singleton never leaks into other tests.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reload_config_to_baseline():
    """Restore ``server.config`` to the ambient env after each test (see test_data_dir)."""
    yield
    import server.config as config

    importlib.reload(config)


def _reload(monkeypatch, *, platform=None, **env):
    """Reload server.config with ARSLAN_DATA_DIR (and friends) controlled."""
    for key in ("ARSLAN_DATA_DIR", "ARSLAN_DB_PATH", "ARSLAN_SPAWNS_DIR"):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    if platform is not None:
        monkeypatch.setattr(sys, "platform", platform)
    import server.config as config

    return importlib.reload(config)


def _subsystem_roots(config):
    """The base dir each subsystem resolves, keyed by a readable name."""
    from server.registry import executors, service
    from server.services import code_sandbox, command_net, html_artifact, skill_import

    return {
        "code_sandbox.sandbox_env": code_sandbox._data_dir() / "sandbox_env",
        "command_net.workspace": command_net._data_dir() / "shell_workspace",
        "html_artifact.artifacts": html_artifact.artifacts_dir(),
        "skill_import.data_dir": skill_import._data_dir(),
        "registry.service.skill_scripts": service._skill_scripts_root(),
        "registry.executors.skill_scripts": executors._skill_scripts_root(),
    }


def test_all_subsystems_under_platform_default_when_unset(monkeypatch):
    """UNSET ARSLAN_DATA_DIR -> every subsystem lives UNDER settings.data_dir (the
    platform app-data dir), NEVER CWD/data. This is the silent-split regression guard."""
    config = _reload(monkeypatch, platform="darwin")
    root = config.settings.data_dir
    expected = (Path.home() / "Library" / "Application Support" / "Arslan").resolve()
    assert root == expected  # sanity: config resolved the platform default
    cwd_data = (Path.cwd() / "data").resolve()

    for name, path in _subsystem_roots(config).items():
        assert path == path.resolve() or path.is_absolute(), name
        # Under the single resolved root...
        assert str(path).startswith(str(root)), f"{name} -> {path} not under {root}"
        # ...and specifically NOT in the CWD-relative ./data (the old default).
        assert not str(path).startswith(str(cwd_data) + "/") and path != cwd_data, (
            f"{name} -> {path} leaked into CWD/data")


def test_all_subsystems_honor_dev_data_dir(monkeypatch):
    """ARSLAN_DATA_DIR=data (the dev flow) -> every subsystem still resolves to
    CWD/data. Nothing about the daily dev flow changes."""
    config = _reload(monkeypatch, ARSLAN_DATA_DIR="data")
    cwd_data = (Path.cwd() / "data").resolve()
    assert config.settings.data_dir == cwd_data

    roots = _subsystem_roots(config)
    assert roots["code_sandbox.sandbox_env"] == cwd_data / "sandbox_env"
    assert roots["command_net.workspace"] == cwd_data / "shell_workspace"
    assert roots["html_artifact.artifacts"] == cwd_data / "artifacts"
    assert roots["skill_import.data_dir"] == cwd_data
    assert roots["registry.service.skill_scripts"] == cwd_data / "skill_scripts"
    assert roots["registry.executors.skill_scripts"] == cwd_data / "skill_scripts"


def test_all_subsystems_honor_absolute_data_dir(monkeypatch, tmp_path):
    """An explicit absolute ARSLAN_DATA_DIR is honored by every subsystem."""
    target = tmp_path / "brain"
    config = _reload(monkeypatch, ARSLAN_DATA_DIR=str(target))
    root = target.resolve()
    for name, path in _subsystem_roots(config).items():
        assert str(path).startswith(str(root)), f"{name} -> {path} not under {root}"


def test_data_dir_accessor_is_live_env_resolved(monkeypatch, tmp_path):
    """``config.data_dir()`` re-resolves from the env at call time (mirroring
    load_settings), so a test that setenv's ARSLAN_DATA_DIR without reloading config
    still points the subsystems at the new dir. This is the reload-safety contract the
    existing skill_scripts/artifact suites rely on."""
    import server.config as config

    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "live"))
    assert config.data_dir() == (tmp_path / "live").resolve()
    # And it shares load_settings' resolver: identical to a freshly-reloaded settings.
    reloaded = importlib.reload(config)
    assert config.data_dir() == reloaded.settings.data_dir
