"""packaging/server_entry.py — the packaged app's process entry (S4.3-a).

The bug this file exists to prevent is invisible on the machine that builds
the app: README.md:54 and CONTRIBUTING.md:43 both instruct developers to
export ARSLAN_DATA_DIR=data, a packaged app inherits the launching shell's
environment, and a relative path resolves against the .app's CWD. A released
build launched from such a shell would quietly use a throwaway directory
instead of the user's real brain — and the developer, whose data lives in the
repo regardless, is the person least likely to notice.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

import pytest

_ENTRY = pathlib.Path(__file__).resolve().parents[2] / "packaging" / "server_entry.py"


def _load_entry():
    """Import server_entry.py by path — packaging/ is not an importable package."""
    spec = importlib.util.spec_from_file_location("_arslan_server_entry", _ENTRY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def entry():
    return _load_entry()


def test_the_entry_script_exists_where_the_pyinstaller_spec_expects_it():
    """Pre-assertion (class 0): everything below is vacuous if this path moved."""
    assert _ENTRY.is_file(), f"{_ENTRY} is missing — the .spec references it by path"


def test_a_developer_data_dir_override_is_stripped(entry, monkeypatch, tmp_path):
    """THE packaging assertion: an inherited ARSLAN_DATA_DIR must not survive.

    Asserting only that the variable is gone would be weak — it would pass for
    an implementation that popped the var but left something else pointing at
    the wrong place. So assert the OUTCOME: the resolved data dir is the
    per-platform app-data path.
    """
    import server.config as config

    monkeypatch.setenv("ARSLAN_DATA_DIR", "data")
    monkeypatch.setenv("HOME", str(tmp_path))

    # Control: while the override is set, resolution really does follow it —
    # otherwise this test could pass against a build where the variable was
    # never honoured in the first place, and would be proving nothing.
    assert config._resolve_data_dir() == pathlib.Path("data").resolve()

    entry._sanitize_env()

    assert "ARSLAN_DATA_DIR" not in os.environ
    resolved = config._resolve_data_dir()
    assert resolved == config._default_data_dir()
    assert "Application Support" in str(resolved) or sys.platform != "darwin"
    assert resolved != pathlib.Path("data").resolve()


def test_an_explicit_secret_key_is_left_alone(entry, monkeypatch):
    """The inverse of the rule above — and the reason it is not "strip all".

    ARSLAN_SECRET_KEY is a legitimate power-user setting. Stripping it would
    make a self-managed key silently unused, and every provider key already
    encrypted under it undecryptable (README.md:103).
    """
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "user-managed-secret")
    entry._sanitize_env()
    assert os.environ.get("ARSLAN_SECRET_KEY") == "user-managed-secret"


def test_the_port_is_announced_before_the_blocking_server_call(entry, monkeypatch):
    """The handshake: the shell cannot find the webview target without it.

    Order matters — uvicorn.run() never returns, so a port printed after it
    is a port never printed. Recording both events in one list pins the
    sequence, not just the presence.
    """
    events: list[str] = []
    captured: dict = {}

    import uvicorn

    monkeypatch.setattr(
        uvicorn, "run", lambda *a, **kw: events.append("served") or captured.update(kw)
    )
    monkeypatch.setattr(
        "builtins.print",
        lambda *a, **kw: events.append(f"printed:{a[0]}|flush={kw.get('flush')}"),
    )
    monkeypatch.setenv("ARSLAN_PORT", "54321")

    entry.main()

    assert len(events) == 2
    assert events[0] == f"printed:{entry.PORT_LINE_PREFIX}54321|flush=True", (
        "the port line must be printed, with flush=True — stdout is a pipe "
        "here, so an unflushed line leaves the shell waiting on a blank window"
    )
    assert events[1] == "served"


def test_the_server_binds_loopback_only(entry, monkeypatch):
    """0.0.0.0 would expose an unauthenticated local API to the whole network.

    server/main.py:85 only *warns* about this combination; a desktop build
    must not be able to reach it at all.
    """
    captured: dict = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: captured.update(kw))
    monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
    monkeypatch.setenv("ARSLAN_PORT", "54321")

    entry.main()

    assert captured["host"] == "127.0.0.1"
    assert captured["host"] != "0.0.0.0"  # noqa: S104 — asserting the absence
    assert captured["port"] == 54321


def test_free_port_returns_a_genuinely_bindable_loopback_port(entry):
    """_free_port in isolation: the OS really did release what it handed back."""
    import socket

    port = entry._free_port()
    assert 1024 < port < 65536
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))  # raises if the OS had not freed it


def test_main_asks_the_os_for_a_port_rather_than_hardcoding_one(entry, monkeypatch):
    """main() must ROUTE THROUGH _free_port — not merely have it available.

    An earlier version of this file only exercised _free_port() directly, so
    replacing main()'s call with a hardcoded 8741 left every test green. A
    fixed port turns "Arslan is already running" — the common case on a
    desktop, not the rare one — into a launch crash.

    Stubbing _free_port to a sentinel is what makes the two designs
    distinguishable: a hardcoded implementation cannot produce the sentinel.
    """
    monkeypatch.delenv("ARSLAN_PORT", raising=False)
    sentinel = 61234
    monkeypatch.setattr(entry, "_free_port", lambda: sentinel)

    captured: dict = {}
    printed: list[str] = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: captured.update(kw))
    monkeypatch.setattr("builtins.print", lambda *a, **kw: printed.append(a[0]))

    entry.main()

    assert captured["port"] == sentinel, (
        "main() served on a port _free_port never produced — it is hardcoded"
    )
    # The announced port must be the SAME one served on; announcing a port
    # the server is not listening to would leave the shell pointing at nothing.
    assert printed == [f"{entry.PORT_LINE_PREFIX}{sentinel}"]


def test_an_explicit_port_env_var_wins_over_the_os_assigned_one(entry, monkeypatch):
    """Control for the test above: proves the env override is still honoured.

    Without this pair, an implementation that ignored ARSLAN_PORT entirely
    would pass the sentinel test and break the escape hatch used for debugging.
    """
    monkeypatch.setenv("ARSLAN_PORT", "5599")
    monkeypatch.setattr(entry, "_free_port", lambda: 61234)

    captured: dict = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: captured.update(kw))
    monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

    entry.main()
    assert captured["port"] == 5599


def test_selftest_names_every_module_that_fails_not_just_the_first(entry, monkeypatch):
    """A selftest that stops at the first failure hides the rest of the damage.

    One bad `excludes` entry usually breaks several modules at once; reporting
    only the first turns one build into N build-fix cycles.
    """
    import builtins

    real = builtins.__import__

    def _blocked(name, *a, **kw):
        if name in ("server.services.deck_pptx", "server.services.ingest"):
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    errs: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **kw: errs.append(str(a[0])))

    assert entry.selftest() == 1
    joined = "\n".join(errs)
    assert "deck_pptx" in joined and "ingest" in joined, (
        f"both failures must be reported, got: {joined}"
    )


def test_selftest_covers_the_module_that_a_bad_excludes_entry_broke(entry):
    """deck_pptx must stay in the required list — it is the regression case.

    PIL looks OCR-only (ingest.py:39,61 are our only direct imports) but
    python-pptx imports it internally; excluding PIL shipped a bundle whose
    /health returned 200 while the deck feature raised ModuleNotFoundError.
    """
    import inspect

    src = inspect.getsource(entry.selftest)
    assert "server.services.deck_pptx" in src


def test_the_lifeline_fires_on_eof_and_only_on_eof(entry):
    """The sidecar must outlive normal input and die on EOF — both halves.

    Asserting only the EOF case would be satisfied by an implementation that
    exits immediately on ANY read, which would kill the sidecar the moment it
    started. Asserting only the keep-reading case would be satisfied by one
    that never exits at all, leaving the orphan this exists to prevent.
    """
    import io

    fired: list[str] = []

    # Lines available, then EOF: the loop must consume all of them first.
    stream = io.StringIO("noise\nmore noise\n")
    entry._watch_stdin(stream, on_eof=lambda: fired.append("exit"))
    assert fired == ["exit"]
    assert stream.read() == "", "the watcher must consume input, not exit on it"

    # A stream that raises (broken pipe) means the parent is gone too.
    class Broken:
        def readline(self):
            raise OSError("broken pipe")

    fired.clear()
    entry._watch_stdin(Broken(), on_eof=lambda: fired.append("exit"))
    assert fired == ["exit"]


def test_the_lifeline_is_inert_outside_a_frozen_build(entry, monkeypatch):
    """Guard against re-introducing the bug that killed the test runner.

    pytest replaces sys.stdin with an object whose readline() returns ""
    immediately; without the frozen check that reads as "parent died" and
    os._exit(0) takes pytest down mid-run. It did, once.
    """
    started: list[object] = []
    import threading

    monkeypatch.setattr(
        threading, "Thread", lambda **kw: started.append(kw) or _NoopThread()
    )
    monkeypatch.delattr(sys, "frozen", raising=False)

    entry._die_when_the_shell_does()

    assert started == [], "the watchdog thread must not start in a source checkout"


class _NoopThread:
    def start(self):  # pragma: no cover — only reached if the guard regresses
        raise AssertionError("watchdog thread started outside a frozen build")


def test_a_frozen_build_enforces_auth_and_owns_the_token_source(entry, monkeypatch):
    """The §3(c) contract, both halves.

    ARSLAN_PACKAGED=1 is what makes token_bootstrap mint and persist a token
    (auth ON); popping ARSLAN_API_TOKEN is what guarantees the token the shell
    reads from <data_dir>/api_token is the one actually in force — an
    inherited env token wins over the file and is never persisted, leaving the
    webview holding nothing while the API demands auth.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/nonexistent", raising=False)
    monkeypatch.delenv("ARSLAN_PACKAGED", raising=False)
    monkeypatch.setenv("ARSLAN_API_TOKEN", "inherited-from-shell")
    monkeypatch.setattr("builtins.print", lambda *a, **kw: None)  # _MEIPASS warning

    entry._sanitize_env()

    assert os.environ.get("ARSLAN_PACKAGED") == "1", (
        "without this, a packaged build runs dev+localhost = UNAUTHENTICATED"
    )
    assert "ARSLAN_API_TOKEN" not in os.environ


def test_a_source_checkout_gets_neither_packaged_flag_nor_token_stripping(entry, monkeypatch):
    """Control: the same call outside a frozen build must not force auth on a
    developer or eat their explicitly-set token."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("ARSLAN_PACKAGED", raising=False)
    monkeypatch.setenv("ARSLAN_API_TOKEN", "dev-chosen-token")

    entry._sanitize_env()

    assert "ARSLAN_PACKAGED" not in os.environ
    assert os.environ.get("ARSLAN_API_TOKEN") == "dev-chosen-token"
