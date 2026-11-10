"""CAP10 (v0.1.64): `verify`, a project's smoke test run once in the sandbox.

The unit tests stub terminal_exec.run and read what verify asked it for: the allowlisted command, a copy as the folder,
offline unless the user allowed the network on a card that offers this time only, and nothing at all where the sandbox
can't start. The real-seatbelt tests run a small Python project's tests through the executor: the result comes back,
and the project's own tests prove that its attempts at the network, at a file outside the folder and at the original
folder were refused. A control runs the same tests outside the sandbox, where those three attempts succeed.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from server.services import command_sandbox, permissions, project_verify, sandbox_proxy, terminal_exec

seatbelt = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                              reason="macOS seatbelt: verify refuses without it")


# ── what it runs: the allowlist ──────────────────────────────────────────────────────────────

def _write(folder: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return folder


def test_package_json_runs_npm_test_and_never_the_scripts_text(tmp_path):
    _write(tmp_path, {"package.json": json.dumps({"scripts": {"test": "echo PLANTED-TEXT && rm -rf ~"}})})
    plan = project_verify.discover(tmp_path)
    assert (plan.runner, plan.command, plan.needs_install) == ("npm", "npm test", False)
    assert "PLANTED" not in plan.command


def test_scripts_other_than_test_are_not_a_way_to_run_it(tmp_path):
    _write(tmp_path, {"package.json": json.dumps({"scripts": {"build": "x", "start": "y", "postinstall": "z",
                                                              "smoke": "w"}})})
    assert project_verify.discover(tmp_path) is None


def test_npms_placeholder_test_script_is_no_test(tmp_path):
    _write(tmp_path, {"package.json": json.dumps(
        {"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}})})
    assert project_verify.discover(tmp_path) is None


def test_dependencies_without_node_modules_need_installing(tmp_path):
    _write(tmp_path, {"package.json": json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"jest": "^29"}})})
    assert project_verify.discover(tmp_path).needs_install is True
    (tmp_path / "node_modules").mkdir()
    assert project_verify.discover(tmp_path).needs_install is False


@pytest.mark.parametrize("files", [
    {"pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"},
    {"pytest.ini": "[pytest]\n"},
    {"setup.cfg": "[tool:pytest]\n"},
    {"tox.ini": "[pytest]\n"},
    {"conftest.py": ""},
    {"tests/test_one.py": "def test_x(): pass\n"},
    {"test/unit/test_two.py": "def test_x(): pass\n"},
    {"test_top.py": "def test_x(): pass\n"},
], ids=["pyproject", "pytest.ini", "setup.cfg", "tox.ini", "conftest", "tests-dir", "test-dir", "top-level"])
def test_python_projects_run_pytest(tmp_path, files):
    plan = project_verify.discover(_write(tmp_path, files))
    assert (plan.runner, plan.command) == ("pytest", "python3 -m pytest -q -x")


def test_a_projects_own_virtualenv_runs_its_pytest(tmp_path):
    _write(tmp_path, {"tests/test_one.py": "", ".venv/bin/python": ""})
    assert project_verify.discover(tmp_path).command == ".venv/bin/python -m pytest -q -x"


def test_a_pyproject_without_pytest_is_not_a_test_suite(tmp_path):
    _write(tmp_path, {"pyproject.toml": "[project]\nname = 'x'\n"})
    assert project_verify.discover(tmp_path) is None


@pytest.mark.parametrize("makefile, command", [
    ("build:\n\tcc x.c\ntest: build\n\t./run\n", "make test"),
    ("check:\n\t./run\n", "make check"),
    ("check:\n\ta\ntest:\n\tb\n", "make test"),
    ("test := yes\nall:\n\ttrue\n", None),
    ("test ::= yes\n", None),
    ("deploy:\n\t./ship\n", None),
])
def test_a_makefile_runs_only_its_test_or_check_target(tmp_path, makefile, command):
    plan = project_verify.discover(_write(tmp_path, {"Makefile": makefile}))
    assert (plan.command if plan else None) == command


def test_package_json_comes_before_pytest_and_make(tmp_path):
    _write(tmp_path, {"Makefile": "test:\n\tx\n", "tests/test_a.py": "",
                      "package.json": json.dumps({"scripts": {"test": "node t.js"}})})
    assert project_verify.discover(tmp_path).command == "npm test"
    (tmp_path / "package.json").unlink()
    assert project_verify.discover(tmp_path).runner == "pytest"


def test_test_files_behind_a_link_are_not_looked_at(tmp_path):
    elsewhere = _write(tmp_path / "elsewhere", {"test_far.py": ""})
    (tmp_path / "proj" / "tests").mkdir(parents=True)
    (tmp_path / "proj" / "tests" / "far").symlink_to(elsewhere)
    assert project_verify.discover(tmp_path / "proj") is None


def test_a_linked_config_file_is_not_read(tmp_path):
    outside = _write(tmp_path / "elsewhere", {"package.json": json.dumps({"scripts": {"test": "x"}})})
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "package.json").symlink_to(outside / "package.json")
    assert project_verify.discover(tmp_path / "proj") is None


# ── the copy ─────────────────────────────────────────────────────────────────────────────────

def test_the_copy_links_dependency_folders_and_skips_caches(tmp_path):
    src = _write(tmp_path / "proj", {"a.py": "x", "pkg/b.py": "y", "node_modules/dep/index.js": "z",
                                     ".git/HEAD": "ref", "pkg/__pycache__/b.pyc": "c", ".pytest_cache/v": "c"})
    (src / "link").symlink_to("a.py")
    project_verify.copy_project(src, tmp_path / "copy")
    copy = tmp_path / "copy"
    assert (copy / "a.py").read_text() == "x" and (copy / "pkg" / "b.py").read_text() == "y"
    assert (copy / "node_modules").is_symlink() and (copy / "node_modules").resolve() == (src / "node_modules").resolve()
    assert (copy / ".git").is_symlink()
    assert not (copy / "pkg" / "__pycache__").exists() and not (copy / ".pytest_cache").exists()
    assert (copy / "link").is_symlink() and str((copy / "link").readlink()) == "a.py"


def test_a_folder_too_big_to_copy_is_refused(tmp_path, monkeypatch):
    src = _write(tmp_path / "proj", {f"f{i}.txt": "x" for i in range(5)})
    monkeypatch.setattr(project_verify, "MAX_FILES", 4)
    with pytest.raises(project_verify.TooBig):
        project_verify.copy_project(src, tmp_path / "copy")


def test_a_folder_too_many_bytes_to_copy_is_refused(tmp_path, monkeypatch):
    src = _write(tmp_path / "proj", {"big.bin": "x" * 2048})
    monkeypatch.setattr(project_verify, "MAX_BYTES", 1024)
    with pytest.raises(project_verify.TooBig):
        project_verify.copy_project(src, tmp_path / "copy")


def test_the_scan_for_test_files_stops_at_its_cap(tmp_path, monkeypatch):
    _write(tmp_path / "proj", {**{f"tests/data{i}.txt": "" for i in range(10)}, "tests/deep/test_late.py": ""})
    assert project_verify.discover(tmp_path / "proj").runner == "pytest"
    monkeypatch.setattr(project_verify, "_SCAN_MAX", 5)
    assert project_verify.discover(tmp_path / "proj") is None


# ── the run, with terminal_exec stubbed ──────────────────────────────────────────────────────

@pytest.fixture
def runs(monkeypatch):
    """Every terminal_exec.run verify starts, with the copy it ran in; each returns a clean pass."""
    seen = []

    async def fake_run(command, *, cwd, timeout_s=120, offline=False, sandbox=False, closed=(), readable=(), **kw):
        seen.append({"command": command, "cwd": Path(cwd), "offline": offline, "sandbox": sandbox,
                     "readable": list(readable), "closed": list(closed),
                     "files": sorted(p.name for p in Path(cwd).iterdir()), "timeout_s": timeout_s})
        return {"ok": True, "exit_code": 0, "stdout": "....\n4 passed in 0.1s\n", "stderr": "", "cwd": str(cwd),
                "sandbox": "workspace", **({"offline": True} if offline else {})}
    async def proxy_port():
        return 49151

    monkeypatch.setattr(terminal_exec, "run", fake_run)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(sandbox_proxy, "port", proxy_port)
    monkeypatch.setattr(sandbox_proxy, "listening_ports", lambda: [8000])   # known: the profile can go online
    return seen


@pytest.fixture
def cards(monkeypatch):
    """The network cards verify asks, answered yes unless a test says no."""
    asked = {"requests": [], "answer": True}

    async def fake_decide(req, ctx):
        asked["requests"].append(req)
        return permissions.Decision(asked["answer"], "user", "once" if asked["answer"] else None,
                                    model_text="" if asked["answer"] else "the user said no")
    monkeypatch.setattr(permissions, "decide", fake_decide)
    return asked


def _project(tmp_path) -> Path:
    return _write(tmp_path / "proj", {"tests/test_a.py": "def test_a(): assert True\n"})


async def _verify(folder, **kw):
    return await project_verify.run(folder, network=kw.pop("network", False), why=kw.pop("why", ""), timeout_s=60,
                                    closed=[], readable=[], conversation_id="c1", job_id=None)


async def test_it_runs_once_offline_in_the_sandbox_on_a_copy_with_no_card(tmp_path, runs, cards):
    proj = _project(tmp_path)
    out = await _verify(proj)
    assert len(runs) == 1 and cards["requests"] == []
    run = runs[0]
    assert run["offline"] is True and run["sandbox"] is True and run["timeout_s"] == 60
    assert run["cwd"] != proj and proj not in run["cwd"].parents and "tests" in run["files"]
    assert proj in run["readable"]                     # the linked folders are read where they are
    assert not run["cwd"].exists()                     # the copy goes with the run
    assert (out["ok"], out["exit_code"], out["command"], out["network"]) == (True, 0, "python3 -m pytest -q -x", "off")
    assert "4 passed" in out["stdout_tail"]


async def test_the_result_is_outside_content(tmp_path, runs, cards):
    from server.orchestrator import untrusted
    from server.registry.tool_defs import TRAITS
    out = await _verify(_project(tmp_path))
    assert out["external"] is True and "not instructions" in out["outside_text"]
    assert TRAITS["verify"].outside is True and untrusted.counts_as_external("verify", {}) is True


async def test_without_the_sandbox_nothing_runs(tmp_path, runs, cards, monkeypatch):
    monkeypatch.setattr(command_sandbox, "available", lambda: False)
    for network in (False, True):
        out = await _verify(_project(tmp_path), network=network)
        assert (out["ok"], out["executed"], out["code"]) == (False, False, "sandbox_unavailable")
    assert runs == [] and cards["requests"] == []


async def test_the_network_is_a_card_for_this_run_only(tmp_path, runs, cards):
    out = await _verify(_project(tmp_path), network=True, why="it downloads a fixture")
    (req,) = cards["requests"]
    assert (req.kind, req.once_only, req.conversation_ok) == ("network", True, False)
    assert permissions.options_for(req) == ["once"] and req.why == "it downloads a fixture"
    assert runs[0]["offline"] is False and out["network"] == "on, this once"


async def test_an_allowed_network_the_profile_could_not_open_is_reported_off(tmp_path, runs, cards, monkeypatch):
    monkeypatch.setattr(sandbox_proxy, "listening_ports", lambda: None)   # the profile then falls back to offline
    out = await _verify(_project(tmp_path), network=True)
    assert runs[0]["offline"] is False and out["network"].startswith("off")


async def test_a_no_on_the_network_card_runs_nothing(tmp_path, runs, cards):
    cards["answer"] = False
    out = await _verify(_project(tmp_path), network=True)
    assert runs == [] and (out["ok"], out["executed"]) == (False, False) and "said no" in out["error"]


async def test_an_allowed_network_with_no_proxy_runs_nothing(tmp_path, runs, cards, monkeypatch):
    async def no_port():
        return None
    monkeypatch.setattr(sandbox_proxy, "port", no_port)
    out = await _verify(_project(tmp_path), network=True)
    assert runs == [] and (out["executed"], out["code"]) == (False, "no_proxy")


async def test_while_wrapping_up_there_is_no_network_and_no_card(tmp_path, runs, cards):
    token = terminal_exec.OFFLINE.set(True)
    try:
        out = await _verify(_project(tmp_path), network=True)
    finally:
        terminal_exec.OFFLINE.reset(token)
    assert runs == [] and cards["requests"] == [] and out["executed"] is False


async def test_no_way_to_run_it_says_what_was_looked_for(tmp_path, runs, cards):
    _write(tmp_path / "proj", {"README.md": "hi"})
    out = await _verify(tmp_path / "proj")
    assert runs == [] and (out["ok"], out["code"]) == (False, "no_runner") and "package.json" in out["error"]


async def test_missing_node_modules_is_needs_dependencies_without_running(tmp_path, runs, cards):
    _write(tmp_path / "proj", {"package.json": json.dumps({"scripts": {"test": "jest"},
                                                           "devDependencies": {"jest": "1"}})})
    out = await _verify(tmp_path / "proj")
    assert runs == [] and out["needs_dependencies"] is True and "needs dependencies installed" in out["error"]


@pytest.mark.parametrize("stderr, exit_code", [
    ("E   ModuleNotFoundError: No module named 'requests'", 1),
    ("/usr/bin/python3: No module named pytest", 1),
    ("Error: Cannot find module 'vitest'", 1),
    ("sh: jest: command not found", 127),
])
async def test_a_missing_dependency_in_the_output_is_reported(tmp_path, runs, cards, monkeypatch, stderr, exit_code):
    async def failing(command, *, cwd, **kw):
        return {"ok": False, "exit_code": exit_code, "stdout": "", "stderr": stderr, "cwd": str(cwd),
                "sandbox": "workspace", "offline": True, "error": f"exit code {exit_code}"}
    monkeypatch.setattr(terminal_exec, "run", failing)
    out = await _verify(_project(tmp_path))
    assert out["needs_dependencies"] is True and "needs dependencies installed" in out["note"]


async def test_an_offline_network_failure_says_how_to_ask_for_the_network(tmp_path, runs, cards, monkeypatch):
    async def failing(command, *, cwd, **kw):
        return {"ok": False, "exit_code": 1, "stdout": "getaddrinfo ENOTFOUND registry.example", "stderr": "",
                "cwd": str(cwd), "sandbox": "workspace", "offline": True, "error": "exit code 1"}
    monkeypatch.setattr(terminal_exec, "run", failing)
    out = await _verify(_project(tmp_path))
    assert out["needs_network"] is True and "network: true" in out["note"] and out["ok"] is False


async def test_a_folder_holding_a_protected_path_is_refused(tmp_path, runs, cards, monkeypatch):
    proj = _project(tmp_path)
    monkeypatch.setattr(command_sandbox, "default_protected", lambda: [proj / "secret"])
    out = await _verify(proj)
    assert runs == [] and out["executed"] is False and out["code"] == "protected"


async def test_the_tail_is_the_end_of_a_long_output(tmp_path, runs, cards, monkeypatch):
    async def long_run(command, *, cwd, **kw):
        lines = "\n".join(f"line {i}" for i in range(5000))
        return {"ok": True, "exit_code": 0, "stdout": lines, "stderr": "", "cwd": str(cwd), "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "run", long_run)
    out = await _verify(_project(tmp_path))
    assert out["stdout_tail"].endswith("line 4999") and "line 10\n" not in out["stdout_tail"]
    assert len(out["stdout_tail"]) <= project_verify.STDOUT_TAIL + 10


async def test_the_stderr_tail_is_the_end_of_a_long_stderr(tmp_path, runs, cards, monkeypatch):
    async def noisy(command, *, cwd, **kw):
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "\n".join(f"warn {i}" for i in range(5000)),
                "cwd": str(cwd), "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "run", noisy)
    out = await _verify(_project(tmp_path))
    assert out["stderr_tail"].endswith("warn 4999") and len(out["stderr_tail"]) <= project_verify.STDERR_TAIL + 10


# ── the card for real: permissions offers this time only, and nothing it stores answers the next one ─────

async def test_a_conversation_answer_on_the_card_is_still_this_time_only(tmp_path, runs, monkeypatch):
    from tests.server.test_workspace_tool_gate import _wire
    engine = await _wire(tmp_path, monkeypatch, workspace=str(tmp_path))
    frames = []

    async def asker(frame):
        frames.append(frame)
        return {"approved": True, "by": "mac", "scope": "conversation", "call_id": frame["call_id"]}
    try:
        with permissions.asking_with(asker):
            await _verify(_project(tmp_path), network=True)
            await _verify(tmp_path / "proj", network=True)
    finally:
        await engine.dispose()
    assert [f["options"] for f in frames] == [["once"], ["once"]]
    assert [r["offline"] for r in runs] == [False, False]


async def test_with_nobody_to_ask_the_network_is_refused_and_nothing_runs(tmp_path, runs, monkeypatch):
    from tests.server.test_workspace_tool_gate import _wire
    engine = await _wire(tmp_path, monkeypatch, workspace=str(tmp_path))
    try:
        out = await _verify(_project(tmp_path), network=True)
    finally:
        await engine.dispose()
    assert runs == [] and out["executed"] is False


# ── the executor and the registry ────────────────────────────────────────────────────────────

async def test_the_executor_takes_a_folder_inside_the_working_folder_only(tmp_path, runs, cards, monkeypatch):
    from server.registry.executors import EXECUTORS
    from tests.server.test_workspace_tool_gate import _wire
    ws = tmp_path / "ws"
    _project(ws)
    _project(tmp_path / "outside")
    engine = await _wire(tmp_path, monkeypatch, workspace=str(ws), default_read=True)
    try:
        inside = await EXECUTORS["verify"].execute({"folder": "proj"})
        escaped = await EXECUTORS["verify"].execute({"folder": str(tmp_path / "outside" / "proj")})
        dotdot = await EXECUTORS["verify"].execute({"folder": "../outside/proj"})
    finally:
        await engine.dispose()
    assert inside["ok"] is True and len(runs) == 1
    assert escaped["ok"] is False and dotdot["ok"] is False and "outside the workspace" in escaped["error"]


async def test_with_desktop_documents_downloads_off_a_closed_folder_inside_is_not_copied(tmp_path, runs, cards,
                                                                                         monkeypatch):
    from server.registry.executors import EXECUTORS
    from server.services import workspace_paths
    from tests.server.test_workspace_tool_gate import _wire
    ws = tmp_path / "ws"
    _write(_project(ws), {"Documents/secret.txt": "closed"})
    closed = ws / "proj" / "Documents"
    monkeypatch.setattr(workspace_paths, "green_roots", lambda: [closed])
    engine = await _wire(tmp_path, monkeypatch, workspace=str(ws), default_read=False)
    try:
        out = await EXECUTORS["verify"].execute({"folder": "proj"})
    finally:
        await engine.dispose()
    assert runs[0]["closed"] == [closed] and "Documents" not in runs[0]["files"] and "tests" in runs[0]["files"]
    assert "1 folder(s)" in out["left_out"]


async def test_the_time_limits_hold(tmp_path, runs, cards, monkeypatch):
    from arslan import execution_budget
    from server.registry.executors import EXECUTORS
    from tests.server.test_workspace_tool_gate import _wire
    _project(tmp_path / "ws")
    engine = await _wire(tmp_path, monkeypatch, workspace=str(tmp_path / "ws"), default_read=True)

    class Left:
        def __init__(self, seconds):
            self.seconds = seconds

        def remaining_seconds(self):
            return self.seconds
    try:
        await EXECUTORS["verify"].execute({"folder": "proj", "timeout_s": 99999})        # clamped to the most
        monkeypatch.setattr(execution_budget, "current", lambda: Left(45))
        await EXECUTORS["verify"].execute({"folder": "proj"})                            # what the turn has left
        monkeypatch.setattr(execution_budget, "current", lambda: Left(31))
        short = await EXECUTORS["verify"].execute({"folder": "proj"})
    finally:
        await engine.dispose()
    assert [r["timeout_s"] for r in runs] == [terminal_exec.MAX_TIMEOUT_S, 15]
    assert (short["code"], short["executed"]) == ("time_limit", False)


def test_verify_is_found_on_demand_and_never_resident():
    from server.orchestrator.arslan import RESIDENT
    from server.registry.executors import EXECUTORS
    from server.registry.tool_defs import TOOLS
    tool = next(t for t in TOOLS if t.name == "verify")
    assert "verify" not in RESIDENT and "verify" in EXECUTORS and tool.host is False
    assert tool.schema["required"] == ["folder"] and tool.schema["additionalProperties"] is False


def test_verify_is_never_offered_in_a_replay():
    from server.services.replay_safety import filter_replay_tools
    assert filter_replay_tools([{"key": "verify"}]) == []


# ── real seatbelt ────────────────────────────────────────────────────────────────────────────

_ESCAPES = '''
import json, pathlib, socket
import pytest

CFG = json.loads((pathlib.Path(__file__).parent / "escapes.json").read_text())


def test_the_network_is_refused():
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", CFG["port"]), 2)


def test_a_write_outside_the_folder_is_refused():
    with pytest.raises(OSError):
        pathlib.Path(CFG["outside"]).write_text("escaped")


def test_a_write_to_the_original_folder_is_refused():
    with pytest.raises(OSError):
        (pathlib.Path(CFG["original"]) / "planted.txt").write_text("escaped")


def test_a_write_in_its_own_copy_works():
    pathlib.Path("made-here.txt").write_text("ok")
    assert pathlib.Path("made-here.txt").read_text() == "ok"
'''


def _real_project(tmp_path: Path, port: int) -> Path:
    """A small Python project with its own .venv, which reads pytest from this test run's environment."""
    import sysconfig
    proj = _write(tmp_path / "ws" / "proj", {
        "pyproject.toml": "[tool.pytest.ini_options]\npythonpath = ['.']\ntestpaths = ['tests']\n",
        "calc.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        "tests/test_escapes.py": textwrap.dedent(_ESCAPES)})
    (proj / "tests" / "escapes.json").write_text(json.dumps(
        {"port": port, "outside": str(tmp_path / "outside.txt"), "original": str(proj)}))
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(proj / ".venv")], check=True)
    (site,) = (proj / ".venv" / "lib").glob("python*/site-packages")
    (site / "this_test_run.pth").write_text(sysconfig.get_paths()["purelib"] + "\n")
    return proj


@pytest.fixture
def listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    srv.setblocking(False)
    yield srv
    srv.close()


def _connected(srv) -> bool:
    try:
        srv.accept()[0].close()
        return True
    except BlockingIOError:
        return False


@pytest.mark.macos
@seatbelt
async def test_real_a_small_projects_tests_run_and_its_escapes_are_refused(tmp_path, monkeypatch, listener):
    from server.registry.executors import EXECUTORS
    from tests.server.test_workspace_tool_gate import _wire
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    proj = _real_project(tmp_path, listener.getsockname()[1])
    before = sorted(p.relative_to(proj) for p in proj.rglob("*") if ".venv" not in p.parts)
    engine = await _wire(tmp_path, monkeypatch, workspace=str(tmp_path / "ws"), default_read=True)
    try:
        out = await EXECUTORS["verify"].execute({"folder": "proj"})
    finally:
        await engine.dispose()
    assert out["command"] == ".venv/bin/python -m pytest -q -x"
    assert (out["ok"], out["exit_code"], out["sandbox"], out["network"]) == (True, 0, "workspace", "off"), out
    assert "5 passed" in out["stdout_tail"] and out["external"] is True
    assert not _connected(listener)
    assert not (tmp_path / "outside.txt").exists() and not (proj / "planted.txt").exists()
    assert sorted(p.relative_to(proj) for p in proj.rglob("*") if ".venv" not in p.parts) == before

    # The control: the same tests outside the sandbox reach the listener and write both files, so they fail.
    control = subprocess.run([str(proj / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-x", "-p",
                              "no:cacheprovider", "tests/test_escapes.py"], cwd=proj, capture_output=True, text=True)
    assert control.returncode == 1 and "DID NOT RAISE" in control.stdout
    assert _connected(listener)


@pytest.mark.macos
@seatbelt
async def test_real_a_failing_test_comes_back_with_its_exit_code_and_tail(tmp_path, monkeypatch, listener):
    from server.registry.executors import EXECUTORS
    from tests.server.test_workspace_tool_gate import _wire
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    proj = _real_project(tmp_path, listener.getsockname()[1])
    (proj / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    engine = await _wire(tmp_path, monkeypatch, workspace=str(tmp_path / "ws"), default_read=True)
    try:
        out = await EXECUTORS["verify"].execute({"folder": "proj"})
    finally:
        await engine.dispose()
    assert (out["ok"], out["exit_code"], out["sandbox"]) == (False, 1, "workspace"), out
    assert "1 failed" in out["stdout_tail"] and "assert -1 == 5" in out["stdout_tail"]
    assert not out.get("needs_dependencies") and not out.get("needs_network")
