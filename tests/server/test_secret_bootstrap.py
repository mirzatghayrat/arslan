"""Unit + integration tests for server.secret_bootstrap (dev-only first-boot secret).

The feature: a keyless DEV boot auto-generates ARSLAN_SECRET_KEY once, persists it
OUTSIDE the data dir (default ~/.arslan/secret_key, override ARSLAN_SECRET_KEY_FILE),
and reuses it on every later boot. prod never touches the file; an explicit env value
always wins; set-but-empty ARSLAN_SECRET_KEY_FILE disables the feature entirely (the
test suites pin that ambient disable at conftest module top so no test can ever write
the real ~/.arslan — tests here opt back in with a tmp path).
"""
from __future__ import annotations

import importlib
import logging
import os
import stat
from pathlib import Path

import pytest

from server import secret_bootstrap

NOT_ROOT = pytest.mark.skipif(
    os.geteuid() == 0, reason="permission-denial checks are meaningless as root"
)


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    """Point the feature at a tmp path whose parent does NOT exist yet.

    The not-yet-existing parent makes the created-dir 0o700 assertion meaningful
    (the bootstrap must never chmod a PRE-existing parent — see the dedicated test).
    """
    p = tmp_path / "vault" / "secret_key"
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, str(p))
    return p


def _boot(env: str = "dev", explicit: str = "", **kw) -> str:
    return secret_bootstrap.bootstrap_secret_key(env=env, explicit=explicit, **kw)


def _own_messages(caplog) -> str:
    return " | ".join(
        r.getMessage() for r in caplog.records if r.name == "server.secret_bootstrap"
    )


# --- generation / reuse ------------------------------------------------------


def test_first_boot_generates_persists_and_discloses(keyfile, caplog):
    with caplog.at_level(logging.WARNING):
        value = _boot()
    assert value
    assert keyfile.read_text(encoding="utf-8") == value
    assert stat.S_IMODE(keyfile.stat().st_mode) == 0o600
    assert stat.S_IMODE(keyfile.parent.stat().st_mode) == 0o700
    text = _own_messages(caplog)
    assert str(keyfile) in text  # discloses WHERE it lives
    assert "two pieces" in text.lower()  # backup = data dir + this file
    assert value not in text  # never echoes the secret itself


def test_second_boot_loads_same_value_without_second_disclosure(keyfile, caplog):
    v1 = _boot()
    caplog.clear()  # drop the first boot's disclosure; only the second boot is under test
    with caplog.at_level(logging.INFO):
        v2 = _boot()
    assert v2 == v1
    text = _own_messages(caplog)
    assert "Generated" not in text
    assert "Loaded ARSLAN_SECRET_KEY from" in text


def test_blank_file_self_heals_and_tightens_perms(keyfile):
    """A blank file (poisoned/failed earlier write) is not a secret — regenerate."""
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text("  \n", encoding="utf-8")
    os.chmod(keyfile, 0o644)
    value = _boot()
    assert value.strip()
    assert keyfile.read_text(encoding="utf-8") == value
    # overwrite of a laxer pre-existing file must end owner-only (trailing chmod)
    assert stat.S_IMODE(keyfile.stat().st_mode) == 0o600


def test_lax_permissions_on_load_are_tightened(keyfile, caplog):
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text("loaded-secret-value", encoding="utf-8")
    os.chmod(keyfile, 0o644)
    with caplog.at_level(logging.INFO):
        assert _boot() == "loaded-secret-value"
    assert stat.S_IMODE(keyfile.stat().st_mode) == 0o600


# --- precedence --------------------------------------------------------------


def test_explicit_env_wins_and_mismatch_warns_without_values(keyfile, caplog):
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text("file-secret-value", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        value = _boot(explicit="env-secret-value")
    assert value == "env-secret-value"
    assert keyfile.read_text(encoding="utf-8") == "file-secret-value"  # never overwritten
    text = _own_messages(caplog)
    assert "differs" in text and str(keyfile) in text  # warns, naming the path only
    assert "env-secret-value" not in text and "file-secret-value" not in text


def test_strip_equivalent_env_and_file_do_not_warn(keyfile, caplog):
    """crypto strips before deriving, so 'abc\\n' vs 'abc' is the SAME key — no warning."""
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text("same-secret", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        value = _boot(explicit="same-secret\n")
    assert value == "same-secret\n"  # verbatim: crypto owns the strip semantics
    assert "differs" not in _own_messages(caplog)


def test_whitespace_only_explicit_is_unset_and_autogenerates(keyfile):
    """crypto treats whitespace-only as UNSET (crypto.py strip) — so does the bootstrap."""
    value = _boot(explicit="   ")
    assert value.strip()
    assert value != "   "


# --- boundaries: prod / disabled --------------------------------------------


def test_prod_never_touches_the_file(keyfile, caplog):
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text("file-secret", encoding="utf-8")
    with caplog.at_level(logging.INFO):
        assert _boot(env="prod") == ""
        assert _boot(env="prod", explicit="env-secret") == "env-secret"
    text = _own_messages(caplog)
    assert "differs" not in text  # no mismatch read/compare in prod
    assert "dev-only" in text  # points out the file env is ignored in prod
    assert keyfile.read_text(encoding="utf-8") == "file-secret"


def test_disabled_set_but_empty_returns_explicit_verbatim(monkeypatch, caplog):
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, "")
    with caplog.at_level(logging.INFO):
        assert _boot() == ""
        assert _boot(explicit=" x ") == " x "
    assert _own_messages(caplog) == ""


# --- path handling -----------------------------------------------------------


def test_default_path_is_home_dotarslan_outside_default_data_dir():
    import server.config as config

    default = secret_bootstrap._resolve_secret_path(None)
    assert default == (Path.home() / ".arslan" / "secret_key").resolve()
    assert not default.is_relative_to(config._default_data_dir().resolve())


def test_tilde_override_is_expanded(monkeypatch, tmp_path):
    """Launchers (systemd/docker env files) pass ~ literally — must expanduser."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, "~/mykey")
    value = _boot()
    assert value
    assert (tmp_path / "mykey").resolve().read_text(encoding="utf-8") == value


def test_preexisting_parent_dir_mode_is_untouched(tmp_path, monkeypatch):
    """Never chmod a directory the bootstrap did not create (could be $HOME)."""
    parent = tmp_path / "shared"
    parent.mkdir()
    os.chmod(parent, 0o755)
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, str(parent / "key"))
    value = _boot()
    assert value
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert stat.S_IMODE((parent / "key").stat().st_mode) == 0o600


def test_generation_inside_data_dir_discloses_honestly(tmp_path, monkeypatch, caplog):
    """Secret landing INSIDE the data dir voids lock-and-box — say so, don't claim it."""
    data = tmp_path / "data"
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, str(data / "secret_key"))
    with caplog.at_level(logging.WARNING):
        value = _boot(data_dir=data)
    assert value
    text = _own_messages(caplog)
    assert "INSIDE" in text
    assert "two pieces" not in text.lower()  # the two-piece claim would be false here


# --- failure modes -----------------------------------------------------------


@NOT_ROOT
def test_unwritable_location_falls_back_empty(tmp_path, monkeypatch, caplog):
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o500)
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, str(ro / "sub" / "key"))
    try:
        with caplog.at_level(logging.WARNING):
            assert _boot() == ""
    finally:
        os.chmod(ro, 0o700)
    assert "Could not persist" in _own_messages(caplog)


@NOT_ROOT
def test_unreadable_existing_file_is_never_overwritten(keyfile, caplog):
    """A transient read error on an EXISTING key must never trigger regenerate+truncate
    — rotating the secret permanently bricks every stored BYOK provider key."""
    keyfile.parent.mkdir(parents=True)
    keyfile.write_text("good-secret", encoding="utf-8")
    os.chmod(keyfile, 0o000)
    try:
        with caplog.at_level(logging.WARNING):
            assert _boot() == ""
    finally:
        os.chmod(keyfile, 0o600)
    assert keyfile.read_text(encoding="utf-8") == "good-secret"
    assert "refusing to regenerate" in _own_messages(caplog)


# --- integration through load_settings ---------------------------------------


def test_load_settings_autogenerates_and_reuses(monkeypatch, tmp_path):
    import server.config as config

    monkeypatch.delenv("ARSLAN_SECRET_KEY", raising=False)
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, str(tmp_path / "sk"))
    cfg = importlib.reload(config)
    first = cfg.settings.secret_key
    assert first
    assert (tmp_path / "sk").read_text(encoding="utf-8") == first
    cfg = importlib.reload(config)
    assert cfg.settings.secret_key == first


def test_load_settings_prod_ignores_persisted_file(monkeypatch, tmp_path):
    import server.config as config

    f = tmp_path / "sk"
    f.write_text("persisted-secret", encoding="utf-8")
    monkeypatch.setenv("ARSLAN_ENV", "prod")
    monkeypatch.delenv("ARSLAN_SECRET_KEY", raising=False)
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, str(f))
    cfg = importlib.reload(config)
    assert cfg.settings.secret_key == ""
