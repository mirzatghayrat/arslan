"""The desktop app ignores the configuration it inherits (⓪Plan, after #364; same class as ARSLAN_ALLOWED_*).

A packaged app inherits the environment of whatever launched it. Each variable here was honoured there and
could move the app: the web folder served as its own origin (the page the shell hands the token to), another
Python run outside the sandbox and trusted for its read roots, another home folder for the file tools, other
run budgets, another spawns folder. Two walls, each tested: the frozen entry drops them, and the code that
reads each one ignores it in the frozen app. A dev run still honours every one. (ARSLAN_PORT is removed by
the shell before it starts the sidecar: desktop/src-tauri/src/lib.rs, `the_sidecar_never_takes_an_inherited_port`.)
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def server_entry():
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        yield importlib.import_module("server_entry")
    finally:
        sys.path.remove(str(ROOT / "packaging"))


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def _keep(monkeypatch, *names):
    """So monkeypatch.undo() puts back what the entry changes. delenv on a variable that is not set records
    nothing to undo, so the entry's ARSLAN_PACKAGED=1 leaked into every later test: set it first, then drop it."""
    for name in names:
        if name in os.environ:
            monkeypatch.setenv(name, os.environ[name])
        else:
            monkeypatch.setenv(name, "")
            monkeypatch.delenv(name)


# ── the frozen entry drops them ─────────────────────────────────────────────

def test_the_frozen_entry_drops_every_inherited_override(server_entry, frozen, monkeypatch):
    names = ("ARSLAN_DATA_DIR", "ARSLAN_DB_PATH", "ARSLAN_API_TOKEN", "ARSLAN_ENV", "ARSLAN_PACKAGED",
             "ARSLAN_SPAWNS_DIR", "ARSLAN_SANDBOX_PYTHON", "ARSLAN_DEFAULT_WORKSPACE",
             "ARSLAN_RUN_MAX_TOKENS", "ARSLAN_RUN_MAX_WALL_SECONDS", "ARSLAN_ALLOWED_ORIGINS", "ARSLAN_ALLOWED_HOSTS")
    _keep(monkeypatch, *names)
    for name in ("ARSLAN_SPAWNS_DIR", "ARSLAN_SANDBOX_PYTHON", "ARSLAN_DEFAULT_WORKSPACE",
                 "ARSLAN_RUN_MAX_TOKENS", "ARSLAN_RUN_MAX_WALL_SECONDS"):
        monkeypatch.setenv(name, "/inherited")
    monkeypatch.setattr(server_entry, "_point_static_dir_into_the_bundle", lambda: None)
    server_entry._sanitize_env()
    for name in ("ARSLAN_SPAWNS_DIR", "ARSLAN_SANDBOX_PYTHON", "ARSLAN_DEFAULT_WORKSPACE",
                 "ARSLAN_RUN_MAX_TOKENS", "ARSLAN_RUN_MAX_WALL_SECONDS"):
        assert os.environ.get(name) is None, name           # one key at a time: never print the environment


# ── ARSLAN_STATIC_DIR: the app's own origin ─────────────────────────────────

def test_the_frozen_app_serves_only_its_own_web_folder(server_entry, frozen, monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "arslan_web").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    _keep(monkeypatch, "ARSLAN_STATIC_DIR")
    monkeypatch.setenv("ARSLAN_STATIC_DIR", str(tmp_path / "somebody-elses-page"))
    server_entry._point_static_dir_into_the_bundle()
    assert os.environ.get("ARSLAN_STATIC_DIR") == str(bundle / "arslan_web")


def test_with_no_web_folder_in_the_bundle_the_inherited_one_is_still_not_served(server_entry, frozen, monkeypatch,
                                                                                  tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "empty-bundle"), raising=False)
    _keep(monkeypatch, "ARSLAN_STATIC_DIR")
    monkeypatch.setenv("ARSLAN_STATIC_DIR", str(tmp_path / "somebody-elses-page"))
    server_entry._point_static_dir_into_the_bundle()
    assert os.environ.get("ARSLAN_STATIC_DIR") is None


def test_a_dev_run_still_serves_the_folder_it_is_given(monkeypatch, tmp_path):
    monkeypatch.setenv("ARSLAN_STATIC_DIR", str(tmp_path / "dist"))
    import server.config as config
    try:
        assert importlib.reload(config).settings.static_dir == str(tmp_path / "dist")
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# ── ARSLAN_SANDBOX_PYTHON: the sandbox's interpreter ────────────────────────

def test_the_frozen_app_runs_only_its_bundled_python(frozen, monkeypatch, tmp_path):
    from server.services import code_sandbox
    real = sys.executable                                                   # a real 3.11+
    app = tmp_path / "Resources" / "sidecar"
    (app / "python_runtime" / "bin").mkdir(parents=True)
    (app / "python_runtime" / "bin" / "python3").symlink_to(real)
    other = tmp_path / "elsewhere" / "python3"
    other.parent.mkdir()
    other.symlink_to(real)                                                  # a working one, just not the bundle's
    monkeypatch.setattr(sys, "executable", str(app / "arslan-server"))
    monkeypatch.setenv("ARSLAN_SANDBOX_PYTHON", str(other))
    assert code_sandbox._host_python() == str(app / "python_runtime" / "bin" / "python3")


def test_with_no_bundled_python_the_inherited_one_is_not_used(frozen, monkeypatch, tmp_path):
    from server.services import code_sandbox
    monkeypatch.setattr(sys, "executable", str(tmp_path / "sidecar" / "arslan-server"))
    monkeypatch.setenv("ARSLAN_SANDBOX_PYTHON", "/usr/bin/python3")
    with pytest.raises(RuntimeError, match="reinstall Arslan"):
        code_sandbox._host_python()


# ── ARSLAN_DEFAULT_WORKSPACE: the file tools' own folder ────────────────────

def test_the_frozen_app_keeps_arslan_s_own_folder(frozen, monkeypatch, tmp_path):
    from server.services import settings_service
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(tmp_path / "elsewhere"))
    assert settings_service.default_workspace() == tmp_path / "home" / "Arslan"


def test_a_dev_run_still_takes_the_test_folder(monkeypatch, tmp_path):
    from server.services import settings_service
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(tmp_path / "w"))
    assert settings_service.default_workspace() == tmp_path / "w"


# ── ARSLAN_RUN_MAX_*: the run budgets ───────────────────────────────────────

def test_the_frozen_app_runs_on_its_own_budgets(frozen, monkeypatch):
    from arslan import execution_budget
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    defaults = execution_budget.tier_limits()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("ARSLAN_RUN_MAX_TOKENS", "999999999")
    monkeypatch.setenv("ARSLAN_RUN_MAX_WALL_SECONDS", "999999")
    assert execution_budget.tier_limits() == defaults


def test_a_dev_run_still_takes_a_bench_budget(monkeypatch):
    from arslan import execution_budget
    monkeypatch.setenv("ARSLAN_RUN_MAX_TOKENS", "1234")
    assert execution_budget.tier_limits().tokens == 1234


# ── ARSLAN_SPAWNS_DIR: where spawns are kept ────────────────────────────────

def test_a_packaged_server_keeps_spawns_in_its_data_dir(monkeypatch, tmp_path):
    import server.config as config
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "elsewhere"))
    try:
        monkeypatch.setenv("ARSLAN_PACKAGED", "1")
        assert importlib.reload(config).settings.spawns_dir == (tmp_path / "data").resolve() / "spawns"
        monkeypatch.delenv("ARSLAN_PACKAGED")
        assert importlib.reload(config).settings.spawns_dir == tmp_path / "elsewhere"      # dev honours it
    finally:
        monkeypatch.undo()
        importlib.reload(config)
