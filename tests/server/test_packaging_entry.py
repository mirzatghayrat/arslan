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


def test_compute_selftest_refuses_source_interpreter(entry, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert entry.compute_selftest() == 1


def test_compute_selftest_verifies_export_and_restores_environment(entry, monkeypatch):
    from server.services import artifact_store, code_sandbox, execution_context

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("ARSLAN_DATA_DIR", "must-survive-selftest")
    monkeypatch.setenv("ARSLAN_SANDBOX_PYTHON", "must-not-be-used")
    before_home = os.environ.get("HOME")
    roots = []

    async def fake_run(code, timeout_s):
        assert execution_context.current_run_id() == 1
        assert "ARSLAN_SANDBOX_PYTHON" not in os.environ
        assert "outside file access was not denied" in code
        roots.append(artifact_store.root())
        return {"ok": True, "sandboxed": True, "network_isolated": True,
                "stdout": "COMPUTE_CANARY_OK", "artifacts": [
                    artifact_store.store_bytes(1, "result.csv", b"x\n1\n2\n3\n"),
                    artifact_store.store_bytes(1, "chart.png", b"\x89PNG\r\n\x1a\n" + b"x" * 200)]}

    monkeypatch.setattr(code_sandbox, "run_python", fake_run)
    assert entry.compute_selftest() == 0
    assert os.environ["ARSLAN_DATA_DIR"] == "must-survive-selftest"
    assert os.environ["ARSLAN_SANDBOX_PYTHON"] == "must-not-be-used"
    assert os.environ.get("HOME") == before_home
    assert execution_context.current_run_id() is None
    assert not roots[0].exists()


@pytest.mark.parametrize("sandboxed", [False, True])
def test_compute_selftest_rejects_unisolated_or_missing_artifacts(entry, monkeypatch, sandboxed):
    from server.services import code_sandbox

    monkeypatch.setattr(sys, "frozen", True, raising=False)

    async def fake_run(code, timeout_s):
        return {"ok": True, "sandboxed": sandboxed, "network_isolated": sandboxed,
                "stdout": "COMPUTE_CANARY_OK", "artifacts": []}

    monkeypatch.setattr(code_sandbox, "run_python", fake_run)
    assert entry.compute_selftest() == 1


def test_compute_selftest_flag_never_starts_server(entry, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["arslan-server", "--compute-selftest"])
    monkeypatch.setattr(entry, "compute_selftest", lambda: 7)
    monkeypatch.setattr(entry, "_sanitize_env", lambda: pytest.fail("must not boot"))
    assert entry.main() == 7


def test_offline_restore_dispatches_without_profile_boot(entry, monkeypatch):
    from server.services import recovery_cli
    arguments = ["--archive", "synthetic.zip", "--new-data-dir", "new", "--new-machine"]
    monkeypatch.setattr(sys, "argv", ["arslan-server", "--restore-offline", *arguments])
    monkeypatch.setattr(entry, "_sanitize_env", lambda: pytest.fail("must not boot"))
    monkeypatch.setattr(entry, "_serve", lambda: pytest.fail("must not serve"))
    def restore(argv):
        assert argv == arguments
        return 9
    monkeypatch.setattr(recovery_cli, "main", restore)
    assert entry.main() == 9


def test_activation_trial_dispatches_only_to_restricted_entry(entry, monkeypatch):
    from server import activation_trial_entry
    monkeypatch.setattr(sys, "argv", ["arslan-server", "--activation-trial"])
    monkeypatch.setattr(entry, "_serve", lambda: pytest.fail("must not serve normal app"))
    def trial(sanitize):
        assert sanitize is entry._sanitize_env
        return 8
    monkeypatch.setattr(activation_trial_entry, "run", trial)
    assert entry.main() == 8


@pytest.fixture
def entry(tmp_path, monkeypatch):
    from dataclasses import replace
    from server import config, profile_paths
    monkeypatch.setattr(config, "settings", replace(config.settings, db_path=str(tmp_path / "entry.db"), data_dir=tmp_path))
    monkeypatch.setattr(profile_paths, "resolve_database", lambda: pathlib.Path(config.settings.db_path))
    monkeypatch.setattr(sys, "argv", ["arslan-server"])
    return _load_entry()


def test_activation_control_dispatch_does_not_start_normal_server(entry, monkeypatch):
    from server import activation_control_entry
    monkeypatch.setattr(sys, "argv", ["arslan-server", "--activation-control"])
    monkeypatch.setattr(entry, "_serve", lambda: pytest.fail("must not serve"))
    def control(sanitize):
        assert sanitize is entry._sanitize_env
        return 9
    monkeypatch.setattr(activation_control_entry, "run", control)
    assert entry.main() == 9


@pytest.mark.parametrize("arguments", [
    ["--typo"], ["restore-offline"], ["--new-machine", "--restore-offline"],
    ["--selftest", "--restore-offline"], ["--compute-selftest", "--selftest"],
    ["--selftest", "private-unrecognized-value"],
    ["--activation-control", "--activation-trial"], ["--activation-control", "private-secret"],
])
def test_ambiguous_arguments_never_start_any_mode(entry, monkeypatch, capsys, arguments):
    monkeypatch.setattr(sys, "argv", ["arslan-server", *arguments])
    for name in ("_sanitize_env", "_serve", "selftest", "compute_selftest"):
        monkeypatch.setattr(entry, name, lambda: pytest.fail("invalid arguments must not run"))
    assert entry.main() == 2
    assert capsys.readouterr().out == "ARSLAN_ERROR=invalid_arguments\n"


def test_packaged_entry_holds_profile_until_server_returns(entry, monkeypatch):
    from server import config
    from server.services.data_profile_lock import hold

    def serve():
        with pytest.raises(ValueError, match="^data_profile_in_use$"):
            with hold(pathlib.Path(config.settings.db_path)):
                pytest.fail("running backend must own its profile")
        return 0

    monkeypatch.setattr(entry, "_serve", serve)
    assert entry.main() == 0
    with hold(pathlib.Path(config.settings.db_path)):
        pass


def test_busy_profile_never_announces_port_or_starts_server(entry, monkeypatch, capsys):
    from server import config
    from server.services.data_profile_lock import hold

    monkeypatch.setattr(entry, "_serve", lambda: pytest.fail("busy profile must not serve"))
    with hold(pathlib.Path(config.settings.db_path)):
        assert entry.main() == 1
    assert capsys.readouterr().out == "ARSLAN_ERROR=data_profile_in_use\n"


def test_pending_activation_refuses_startup_before_recreating_profile(entry, monkeypatch, capsys, tmp_path):
    from dataclasses import replace
    from server import config
    from server.services.data_profile_lock import activation_record_path

    database = tmp_path / "temporarily-absent" / "arslan.db"
    monkeypatch.setattr(config, "settings", replace(config.settings, db_path=str(database)))
    monkeypatch.setenv("ARSLAN_DB_PATH", str(database))
    record = activation_record_path(database)
    record.write_text("pending record presence is enough to refuse boot")
    monkeypatch.setattr(entry, "_serve", lambda: pytest.fail("pending activation must not serve"))
    assert entry.main() == 1
    assert capsys.readouterr().out == "ARSLAN_ERROR=data_profile_recovery_required\n"
    assert not database.parent.exists()
    assert record.read_text() == "pending record presence is enough to refuse boot"


@pytest.mark.parametrize("error", [ValueError("private diagnostic"), OSError("private path"),
                                  OSError("data_profile_recovery_required")])
def test_profile_lock_failures_do_not_expose_untrusted_diagnostics(entry, monkeypatch, capsys, error):
    from server.services import data_profile_lock

    def refuse(database):
        raise error

    monkeypatch.setattr(data_profile_lock, "hold", refuse)
    monkeypatch.setattr(entry, "_serve", lambda: pytest.fail("unavailable profile must not serve"))
    assert entry.main() == 1
    assert capsys.readouterr().out == "ARSLAN_ERROR=data_profile_unavailable\n"


@pytest.mark.parametrize("reason", ["pending", "busy"])
def test_refused_fresh_process_does_not_bootstrap_secret(tmp_path, reason):
    from contextlib import nullcontext
    import subprocess
    from server.services.data_profile_lock import activation_record_path, hold

    home = tmp_path / "home"
    home.mkdir()
    if sys.platform == "darwin":
        database = home / "Library/Application Support/Arslan/arslan.db"
    elif sys.platform == "win32":
        pytest.skip("profile lock is POSIX-only")
    else:
        database = home / ".local/share/Arslan/arslan.db"
    database.parent.parent.mkdir(parents=True)
    record = activation_record_path(database)
    if reason == "pending":
        record.write_text("synthetic pending operation")
    code = (
        "import importlib.util,sys; "
        f"s=importlib.util.spec_from_file_location('entry',{str(_ENTRY)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "m._serve=lambda: (_ for _ in ()).throw(AssertionError('must not serve')); "
        "assert 'server.config' not in sys.modules; "
        "assert m.main()==1; assert 'server.config' not in sys.modules"
    )
    with hold(database) if reason == "busy" else nullcontext():
        result = subprocess.run([sys.executable, "-c", code], cwd=_ENTRY.parents[1],
                                env={"PATH": os.environ["PATH"], "HOME": str(home),
                                     "ARSLAN_DB_PATH": str(database), "ARSLAN_DATA_DIR": str(database.parent)},
                                capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    expected = "data_profile_in_use" if reason == "busy" else "data_profile_recovery_required"
    assert result.stdout == f"ARSLAN_ERROR={expected}\n".encode()
    assert not (home / ".arslan").exists()
    assert not database.exists()
    if reason == "pending":
        assert not database.parent.exists()
        assert record.read_text() == "synthetic pending operation"


def test_the_entry_script_exists_where_the_pyinstaller_spec_expects_it():
    """Pre-assertion (class 0): everything below is vacuous if this path moved."""
    assert _ENTRY.is_file(), f"{_ENTRY} is missing — the .spec references it by path"


def test_mcp_collection_excludes_only_the_optional_developer_cli():
    import ast

    tree = ast.parse(_ENTRY.with_name("arslan-server.spec").read_text())
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "collect_submodules"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "mcp")
    predicate = next(keyword.value for keyword in call.keywords if keyword.arg == "filter")
    include = eval(compile(ast.Expression(predicate), "<packaging MCP filter>", "eval"))
    assert not include("mcp.cli")
    assert not include("mcp.cli.cli")
    for name in ("mcp", "mcp.client", "mcp.client.stdio", "mcp.client.auth", "mcp.server.fastmcp", "mcp.shared.auth"):
        assert include(name), name


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

    from types import SimpleNamespace
    monkeypatch.setattr(uvicorn, "Server", lambda config: SimpleNamespace(
        run=lambda: events.append("served") or captured.update(vars(config))))
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

    from types import SimpleNamespace
    monkeypatch.setattr(uvicorn, "Server", lambda config: SimpleNamespace(run=lambda: captured.update(vars(config))))
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


def test_main_routes_through_the_port_chooser_rather_than_hardcoding_one(entry, monkeypatch):
    """main() must ROUTE THROUGH the chooser — not merely have it available.

    An earlier version of this file only exercised the helper directly, so
    replacing main()'s call with a literal left every test green.

    🔴 Gate item ⑦ inverted this test's SUBJECT while keeping its concern. It
    used to stub `_free_port` and its docstring warned that a fixed port turns
    "Arslan is already running" into a launch crash. That worry was right, and
    `choose_port` answers it by FALLING BACK — asserted in
    test_it_falls_back_rather_than_refusing_to_start. What the old ephemeral
    port cost instead was the user's conversation list: a new origin every
    launch, and localStorage is partitioned by origin.
    """
    monkeypatch.delenv("ARSLAN_PORT", raising=False)
    sentinel = 61234
    monkeypatch.setattr(entry, "choose_port", lambda: sentinel)

    captured: dict = {}
    printed: list[str] = []
    import uvicorn

    from types import SimpleNamespace
    monkeypatch.setattr(uvicorn, "Server", lambda config: SimpleNamespace(run=lambda: captured.update(vars(config))))
    monkeypatch.setattr("builtins.print", lambda *a, **kw: printed.append(a[0]))

    entry.main()

    assert captured["port"] == sentinel, (
        "main() served on a port choose_port never produced — it is hardcoded"
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
    monkeypatch.setattr(entry, "choose_port", lambda: 61234)

    captured: dict = {}
    import uvicorn

    from types import SimpleNamespace
    monkeypatch.setattr(uvicorn, "Server", lambda config: SimpleNamespace(run=lambda: captured.update(vars(config))))
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


def test_webpage_resource_probe_extracts_without_network(entry):
    probe = dict((name, check) for name, check, _ in entry._lazy_resource_probes())["webpage extraction data"]
    ok, detail = probe()
    assert ok, detail


def test_webpage_resource_probe_rejects_missing_stoplists(entry, monkeypatch):
    import justext

    monkeypatch.setattr(justext, "get_stoplists", lambda: frozenset())
    probe = dict((name, check) for name, check, _ in entry._lazy_resource_probes())["webpage extraction data"]
    assert probe()[0] is False


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


def test_exact_parent_shutdown_request_does_not_trigger_abrupt_eof(entry):
    import io
    events = []
    entry._watch_stdin(io.StringIO("ARSLAN_SHUTDOWN\n"),
                      on_eof=lambda: events.append("abrupt"), on_shutdown=lambda: events.append("graceful"))
    assert events == ["graceful"]
    for line in ("ARSLAN_SHUTDOWN extra\n", "ARSLAN_SHUTDOWN", "ARSLAN_SHUTDOWN\r\n"):
        events.clear()
        entry._watch_stdin(io.StringIO(line), on_eof=lambda: events.append("abrupt"),
                          on_shutdown=lambda: events.append("graceful"))
        assert events == ["abrupt"]


@pytest.mark.parametrize("early,failed,complete,expected", [
    (False, False, True, 0), (True, False, True, 1), (False, True, True, 1), (False, False, False, 1),
])
def test_requested_shutdown_requires_completed_lifespan(entry, monkeypatch, capsys, early, failed, complete, expected):
    from types import SimpleNamespace
    import uvicorn
    from server.main import app
    monkeypatch.setattr(app.state, "shutdown_complete", complete, raising=False)
    monkeypatch.setenv("ARSLAN_PORT", "54321")
    callback = []
    monkeypatch.setattr(entry, "_die_when_the_shell_does", lambda on_shutdown: callback.append(on_shutdown))
    server = SimpleNamespace(started=not early, should_exit=False,
                             lifespan=SimpleNamespace(shutdown_failed=failed))
    def run():
        callback[0]()
        server.started = True
    server.run = run
    monkeypatch.setattr(uvicorn, "Server", lambda config: server)
    assert entry._serve() == expected
    assert server.should_exit
    output = capsys.readouterr().out
    assert ("ARSLAN_STOPPED=1\n" in output) is (expected == 0)


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


# ---------------------------------------------------------------------------
# Gate item ⑦, half (i) — the port must be STABLE
# ---------------------------------------------------------------------------

def _a_free_port() -> int:
    """A port this test owns, so the assertions do not depend on what else is
    running on the developer's machine.

    🔴 The first version of these two tests asserted against the REAL
    DEFAULT_PORT, so they went red the moment the user had Arslan open — which
    is most of the time for the person most likely to run them. CI never saw it
    because CI has no app running. A test whose result depends on whether an
    unrelated program is open is not testing the thing it names.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_the_default_port_is_fixed_not_ephemeral(entry, monkeypatch):
    """The window loads `http://127.0.0.1:<port>`, and WebKit partitions
    localStorage by ORIGIN — of which the port is part. An ephemeral port meant
    a fresh, empty store on every launch, and the conversation list lived there
    and nowhere else. Measured in the user's packaged database: 10
    conversations, 74 messages, five distinct thread ids in a single day, while
    the sidebar showed one chat.

    The server-side listing is what RECOVERS conversations; this is what stops
    new ones being orphaned, and it also stops every other origin-scoped thing
    (theme, panel state) resetting each launch.
    """
    # The shipped constant is what matters for the CLAIM…
    assert isinstance(entry.DEFAULT_PORT, int)
    assert 1024 < entry.DEFAULT_PORT < 65536
    # …but the BEHAVIOUR is checked against a port this test owns, so a running
    # Arslan on the real one cannot decide the outcome.
    free = _a_free_port()
    monkeypatch.setattr(entry, "DEFAULT_PORT", free)
    assert entry.choose_port() == free


def test_it_falls_back_rather_than_refusing_to_start(entry, monkeypatch):
    """Discriminating: a version that just returned DEFAULT_PORT would pass the
    test above and fail to launch whenever anything else holds the port — an
    annoyance turned into a dead app. Survivable precisely BECAUSE the listing
    is server-side: a different origin costs some UI state, not the history.

    🔴 Binds a port this test OWNS rather than the real DEFAULT_PORT. The first
    version bound 47317 directly, so it blew up with EADDRINUSE whenever the
    user had Arslan running — which is most of the time for the person most
    likely to run these tests. CI never noticed because CI has no app open.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.listen(1)
        monkeypatch.setattr(entry, "DEFAULT_PORT", port)
        fallback = entry.choose_port()
    assert fallback != port
    assert 1024 < fallback < 65536


def test_the_launch_path_actually_calls_it(entry):
    """The shape that keeps catching me: a correct helper with no caller."""
    import inspect

    src = inspect.getsource(entry)
    assert "choose_port()" in src
    assert 'os.environ.get("ARSLAN_PORT") or choose_port()' in src


def _leave_a_port_in_time_wait() -> int:
    """Return a port left in TIME_WAIT, the way a just-exited Arslan leaves one.

    The server side closes LAST, which is what puts the listener's tuple into
    TIME_WAIT — exactly the state the next launch finds a moment later.
    """
    import socket

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)
    cli = socket.create_connection(("127.0.0.1", port))
    con, _ = srv.accept()
    cli.close()
    con.close()
    srv.close()
    return port


def test_the_probe_is_no_stricter_than_the_server_it_probes_for(entry, monkeypatch):
    """🔴 The probe must bind the way uvicorn binds, or it rejects usable ports.

    Shipped in v0.1.15 and observed failing on the user's machine the same day:
    the app was v0.1.15, DEFAULT_PORT was free, and the sidecar still came up on
    an ephemeral port. Cause — `choose_port` test-bound WITHOUT `SO_REUSEADDR`
    while uvicorn binds WITH it, so a port left in TIME_WAIT by the previous
    instance looked taken to the probe and usable to the server.

    The failure mode is the ugly one: a probe that is too LOOSE gives a false
    green, which is the familiar disease; one that is too STRICT gives a false
    NEGATIVE, and this false negative fires precisely on RESTART — the single
    scenario the fixed port exists to protect.

    Verified before writing the fix: on a TIME_WAIT port, bind without
    SO_REUSEADDR fails with errno 48; bind with it succeeds.
    """
    port = _leave_a_port_in_time_wait()
    monkeypatch.setattr(entry, "DEFAULT_PORT", port)

    assert entry.choose_port() == port, (
        "choose_port abandoned a port that uvicorn could have bound — the probe "
        "is stricter than its consumer"
    )


def test_a_genuinely_held_port_still_falls_back(entry, monkeypatch):
    """Discriminating: setting SO_REUSEADDR must not turn the probe into a
    rubber stamp. A port with a LIVE listener on it is really unusable, and the
    fallback still has to fire."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("127.0.0.1", 0))
        port = held.getsockname()[1]
        held.listen(1)
        monkeypatch.setattr(entry, "DEFAULT_PORT", port)
        chosen = entry.choose_port()

    assert chosen != port, "the probe accepted a port with a live listener on it"
    assert 1024 < chosen < 65536
