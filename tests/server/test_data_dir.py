"""S1 OSS-safety: the default data dir must be a stable per-platform app-data
directory, NOT a CWD-relative ``./data``.

Rationale: the SQLite "brain" lived at ``./data/arslan.db`` resolved against
whatever directory uvicorn happened to be launched from. A stranger who packaged
the app and launched it from a different folder got a fresh empty DB and thought
their data was lost. When ``ARSLAN_DATA_DIR`` is UNSET we now resolve a proper
OS app-data dir; when it IS set (including the dev flow's ``=data``) we honor it
verbatim so nothing about the daily dev flow changes.

Each test reloads ``server.config`` under a monkeypatched env/platform (matching
test_settings_hardening / test_middleware_security) and the autouse fixture
reloads config back to the ambient baseline afterwards so the mutated
module-singleton never leaks into other tests.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reload_config_to_baseline(monkeypatch):
    """Restore ``server.config`` to the ambient env after each test.

    These tests mutate ARSLAN_DATA_DIR / sys.platform and reload the config
    module (which recomputes the ``settings`` singleton). The env + platform are
    restored HERE, before the reload, and not left to monkeypatch's own teardown:
    an autouse fixture in tests/server/conftest.py instantiates ``monkeypatch``
    before this one, so monkeypatch finalizes AFTER it. Relying on that order
    (as this fixture used to) rebuilt the "baseline" from the test's own env and
    left ``settings`` on the platform dir; test_dispatcher_override then mkdir'd
    ``spawns/S/.evolution`` under ``~/Library/Application Support/Arslan``.
    """
    yield
    monkeypatch.undo()
    import server.config as config

    importlib.reload(config)


def _reload(monkeypatch, *, platform=None, **env):
    """Reload server.config with ARSLAN_DATA_DIR (and friends) controlled.

    Clears the path-related env vars first so the resolution under test is not
    shadowed by the ambient ``ARSLAN_DATA_DIR=data`` the suite runs with, then
    applies the requested overrides + optional ``sys.platform``.
    """
    for key in ("ARSLAN_DATA_DIR", "ARSLAN_DB_PATH", "ARSLAN_SPAWNS_DIR"):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    if platform is not None:
        monkeypatch.setattr(sys, "platform", platform)
    import server.config as config

    return importlib.reload(config)


# --- unset -> per-platform app-data dir -------------------------------------


def test_default_macos_uses_application_support(monkeypatch):
    config = _reload(monkeypatch, platform="darwin")
    expected = (Path.home() / "Library" / "Application Support" / "Arslan").resolve()
    assert config.settings.data_dir == expected
    assert config.settings.data_dir.is_absolute()
    # db + spawns hang off the resolved app-data dir.
    assert Path(config.settings.db_path) == expected / "arslan.db"


def test_default_linux_uses_xdg_local_share(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    config = _reload(monkeypatch, platform="linux")
    expected = (Path.home() / ".local" / "share" / "Arslan").resolve()
    assert config.settings.data_dir == expected
    assert config.settings.data_dir.is_absolute()


def test_default_linux_respects_xdg_data_home(monkeypatch, tmp_path):
    xdg = tmp_path / "xdg"
    config = _reload(monkeypatch, platform="linux", XDG_DATA_HOME=str(xdg))
    expected = (xdg / "Arslan").resolve()
    assert config.settings.data_dir == expected
    assert config.settings.data_dir.is_absolute()


def test_default_windows_uses_appdata(monkeypatch, tmp_path):
    appdata = tmp_path / "Roaming"
    config = _reload(monkeypatch, platform="win32", APPDATA=str(appdata))
    expected = (appdata / "Arslan").resolve()
    assert config.settings.data_dir == expected
    assert config.settings.data_dir.is_absolute()


# --- set -> honored verbatim (dev flow unchanged) ---------------------------


def test_data_dir_set_is_honored_verbatim(monkeypatch):
    """The dev flow runs with ARSLAN_DATA_DIR=data — it must keep pointing at the
    CWD ``./data`` (resolved to absolute for stable I/O + logging), NOT relocate to
    a platform app-data dir."""
    config = _reload(monkeypatch, ARSLAN_DATA_DIR="data")
    expected = (Path.cwd() / "data").resolve()
    assert config.settings.data_dir == expected
    assert config.settings.data_dir.is_absolute()
    assert config.settings.data_dir == Path("data").resolve()
    assert Path(config.settings.db_path) == expected / "arslan.db"


def test_data_dir_set_absolute_is_honored(monkeypatch, tmp_path):
    target = tmp_path / "custom_brain"
    config = _reload(monkeypatch, ARSLAN_DATA_DIR=str(target))
    assert config.settings.data_dir == target.resolve()
    assert Path(config.settings.db_path) == target.resolve() / "arslan.db"


def test_data_dir_expands_user_and_vars(monkeypatch, tmp_path):
    """A set value with ``~``/``$VAR`` is expanded, not treated literally."""
    monkeypatch.setenv("MY_BRAIN_ROOT", str(tmp_path))
    config = _reload(monkeypatch, ARSLAN_DATA_DIR="$MY_BRAIN_ROOT/brain")
    assert config.settings.data_dir == (tmp_path / "brain").resolve()


def test_boot_logs_resolved_absolute_db_path(monkeypatch, caplog, tmp_path):
    """The boot line names the RESOLVED ABSOLUTE data dir + db path (info-level).

    Covers the ``server.main._log_data_location`` helper the lifespan calls right
    after creating the data dir — the message a stranger relies on to find where
    their brain actually lives."""
    import logging

    target = tmp_path / "brain"
    config = _reload(monkeypatch, ARSLAN_DATA_DIR=str(target))
    import server.main as main

    with caplog.at_level(logging.INFO, logger="server.main"):
        main._log_data_location(config.settings)

    line = next(r.getMessage() for r in caplog.records if "Arslan data dir" in r.getMessage())
    assert str(target.resolve()) in line
    assert str((target / "arslan.db").resolve()) in line


def test_default_data_dir_import_has_no_filesystem_side_effect(monkeypatch, tmp_path):
    """Reloading config must NOT create the platform dir (surprising import I/O
    that would litter ~/Library during tests); the app creates it at boot.

    HOME is a temp dir, so the platform default is a path that cannot exist yet and
    the check is exact for both branches. This used to probe
    ``<real platform dir>/does_not_exist_probe`` — the user's own data dir as the
    fixture — and failed on 2026-10-03 because another test's leak had created it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    config = _reload(monkeypatch, platform="darwin")
    expected = (tmp_path / "Library" / "Application Support" / "Arslan").resolve()
    assert config.settings.data_dir == expected  # the unset branch, under the temp HOME
    assert not expected.exists()

    probe = tmp_path / "set_but_absent"
    config = _reload(monkeypatch, platform="darwin", ARSLAN_DATA_DIR=str(probe))
    assert config.settings.data_dir == probe.resolve()
    assert list(tmp_path.iterdir()) == []
