"""A process started from a Claude Code session never opens the key file unless it is named.

Twice on 2026-11-07 a session's process read the real ``~/.arslan/secret_key``: a bare
``python -c 'import server...'`` with the real HOME, and the explicit-key mismatch check, which reads
the file only to compare it. Claude Code sets ``CLAUDECODE=1`` in every process it starts. With that
marker and ``ARSLAN_SECRET_KEY_FILE`` unset, the secret bootstrap now does what the set-but-empty off
switch does: no stat, no read, no write, no comparison. It logs one warning naming the opt-in instead.
Naming a path, or the empty off switch, keeps its meaning, and without the marker nothing changes.

Every case here sets or clears both variables itself (the suite's conftest pins
``ARSLAN_SECRET_KEY_FILE=""`` and this machine's own run may carry ``CLAUDECODE=1``), and HOME is a
scratch folder, so the real ``~/.arslan`` is never resolved.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys

import pytest

from server import secret_bootstrap

MARKER = "CLAUDECODE"
FILE_VALUE = "file-value-for-the-test"
EXPLICIT_VALUE = "explicit-value-for-the-test"

# Opens are recorded by an audit hook (it sees builtins.open, io.open, os.open and Path.read_text);
# an audit hook cannot be removed, so it records only while a case switches it on.
_OPENS: list[tuple[str, str]] | None = None


def _audit(event, args):
    if _OPENS is not None and event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        _OPENS.append(("open", os.fsdecode(args[0])))


sys.addaudithook(_audit)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A scratch HOME holding a key file at the default place, ``~/.arslan/secret_key``."""
    home = tmp_path.resolve() / "home"
    (home / ".arslan").mkdir(parents=True)
    (home / ".arslan" / "secret_key").write_text(FILE_VALUE, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def touched(monkeypatch):
    """Every (kind, path) opened or stat'ed while the case runs (os.stat/os.lstat cover exists() and resolve())."""
    global _OPENS
    seen: list[tuple[str, str]] = []
    real_stat, real_lstat = os.stat, os.lstat

    def stat(path, *args, **kwargs):
        if not isinstance(path, int):
            seen.append(("stat", os.fsdecode(path)))
        return real_stat(path, *args, **kwargs)

    def lstat(path, *args, **kwargs):
        if not isinstance(path, int):
            seen.append(("lstat", os.fsdecode(path)))
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os, "lstat", lstat)
    _OPENS = seen
    try:
        yield seen
    finally:
        _OPENS = None


def _under(seen: list[tuple[str, str]], folder) -> list[tuple[str, str]]:
    """`folder` is already resolved (the fixtures resolve tmp_path before recording starts): resolving it here
    would itself lstat it while the recorder is on."""
    root = str(folder)
    return [(kind, p) for kind, p in seen if p == root or p.startswith(root + os.sep)]


def _opened(seen: list[tuple[str, str]], path) -> bool:
    return ("open", str(path)) in seen


def _own(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "server.secret_bootstrap"]


def _session(monkeypatch):
    monkeypatch.setenv(MARKER, "1")
    monkeypatch.delenv(secret_bootstrap.SECRET_FILE_ENV, raising=False)


# --- in a session, with the key file variable unset ------------------------------------------------------


@pytest.mark.parametrize("explicit, expected", [
    pytest.param(EXPLICIT_VALUE, EXPLICIT_VALUE, id="explicit-key"),
    pytest.param("", "", id="no-key"),
])
def test_a_session_opens_nothing_under_home_and_says_how_to_opt_in(home, touched, monkeypatch, caplog,
                                                                    explicit, expected):
    _session(monkeypatch)
    with caplog.at_level(logging.INFO):
        value = secret_bootstrap.bootstrap_secret_key(explicit=explicit, data_dir=home / "data")
    assert value == expected
    assert _under(touched, home) == []                      # no open, no stat: not even the folder
    assert (home / ".arslan" / "secret_key").read_text(encoding="utf-8") == FILE_VALUE
    own = _own(caplog)
    assert [r.levelno for r in own] == [logging.WARNING]   # exactly one line, and a loud one
    text = own[0].getMessage()
    assert "Claude Code" in text and "Set ARSLAN_SECRET_KEY_FILE to the key file's path" in text
    assert FILE_VALUE not in caplog.text and EXPLICIT_VALUE not in caplog.text


def test_a_session_without_a_key_file_creates_none(tmp_path, touched, monkeypatch):
    """The keyless first boot would otherwise generate and write a key into the real home."""
    home = tmp_path.resolve() / "empty-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _session(monkeypatch)
    assert secret_bootstrap.bootstrap_secret_key(explicit="") == ""
    assert _under(touched, home) == []
    assert list(home.iterdir()) == []


def test_a_session_server_config_gets_no_key_from_the_file(home, touched, monkeypatch):
    """Through load_settings, as `import server...` or a dev server started from a session runs it."""
    import server.config as config

    _session(monkeypatch)
    monkeypatch.delenv("ARSLAN_SECRET_KEY", raising=False)
    try:
        cfg = importlib.reload(config)
        assert cfg.settings.secret_key == ""
        assert _under(touched, home / ".arslan") == []
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# --- in a session, with the variable set: as today ----------------------------------------------------------


def test_a_session_that_names_the_file_reads_it(home, touched, monkeypatch, caplog):
    keyfile = home / ".arslan" / "secret_key"
    monkeypatch.setenv(MARKER, "1")
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, str(keyfile))
    with caplog.at_level(logging.INFO):
        assert secret_bootstrap.bootstrap_secret_key(explicit="") == FILE_VALUE
        assert secret_bootstrap.bootstrap_secret_key(explicit=EXPLICIT_VALUE) == EXPLICIT_VALUE
    assert _opened(touched, keyfile)                        # opened, as without the marker
    text = " | ".join(r.getMessage() for r in _own(caplog))
    assert "Claude Code" not in text
    assert "differs" in text                                # the comparison still runs when asked for
    assert FILE_VALUE not in caplog.text and EXPLICIT_VALUE not in caplog.text


def test_a_session_with_the_empty_off_switch_stays_off_and_quiet(home, touched, monkeypatch, caplog):
    monkeypatch.setenv(MARKER, "1")
    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, "")
    with caplog.at_level(logging.INFO):
        assert secret_bootstrap.bootstrap_secret_key(explicit="") == ""
        assert secret_bootstrap.bootstrap_secret_key(explicit=" x ") == " x "
    assert _under(touched, home) == []
    assert _own(caplog) == []


# --- without the marker: exactly as today ---------------------------------------------------------------------


@pytest.mark.parametrize("marker", [None, "0"], ids=["no-marker", "marker-not-1"])
def test_without_the_marker_the_default_file_is_read_and_compared(home, touched, monkeypatch, caplog, marker):
    """The packaged app and a terminal never carry CLAUDECODE=1. This also proves the recorder sees opens."""
    keyfile = home / ".arslan" / "secret_key"
    if marker is None:
        monkeypatch.delenv(MARKER, raising=False)
    else:
        monkeypatch.setenv(MARKER, marker)
    monkeypatch.delenv(secret_bootstrap.SECRET_FILE_ENV, raising=False)
    with caplog.at_level(logging.INFO):
        assert secret_bootstrap.bootstrap_secret_key(explicit="") == FILE_VALUE
        assert secret_bootstrap.bootstrap_secret_key(explicit=EXPLICIT_VALUE) == EXPLICIT_VALUE
    assert _opened(touched, keyfile)                        # the path is already resolved (fixture)
    text = " | ".join(r.getMessage() for r in _own(caplog))
    assert "Claude Code" not in text and "differs" in text


# --- what a session-started dev server says when stored keys do not decrypt -------------------------------------


def test_the_undecryptable_keys_line_names_the_opt_in_only_in_a_session_without_it(monkeypatch):
    import server.main as main

    _session(monkeypatch)
    in_session = main._UNDECRYPTABLE_KEYS_MSG + main._session_key_file_hint()
    assert "Claude Code" in in_session and "Set ARSLAN_SECRET_KEY_FILE to the key file's path" in in_session
    assert "2 stored provider" in in_session % 2            # still one %d and nothing else to format

    monkeypatch.setenv(secret_bootstrap.SECRET_FILE_ENV, "/some/key/file")
    assert main._session_key_file_hint() == ""
    monkeypatch.delenv(secret_bootstrap.SECRET_FILE_ENV)
    monkeypatch.delenv(MARKER)
    assert main._session_key_file_hint() == ""
