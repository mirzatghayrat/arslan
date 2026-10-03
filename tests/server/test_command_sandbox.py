"""run_command's workspace sandbox (0.1.51 P3): the profile, the stop detector,
the conversation grant, and — on macOS — what the kernel actually refuses."""
import json
import socket
import sys
from pathlib import Path

import pytest

from server.services import command_sandbox, terminal_exec

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")


@pytest.fixture(autouse=True)
def fresh():
    command_sandbox._reset_for_tests()
    yield
    command_sandbox._reset_for_tests()


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A workspace, a folder outside it, and a protected folder INSIDE a writable
    one (temp) — the case only rule order can get right."""
    ws, outside = tmp_path / "ws", Path.home() / f".arslan-sbx-test-{tmp_path.name}"
    ws.mkdir()
    outside.mkdir()
    secret = ws / "secret"
    secret.mkdir()
    (secret / "key").write_text("hush")
    monkeypatch.setattr(command_sandbox, "default_protected", lambda: [secret.resolve()])
    yield ws, outside, secret
    for p in sorted(outside.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    outside.rmdir()


# ── the profile (any platform) ────────────────────────────────────────────────

def test_rule_order_denies_writes_reopens_folders_and_closes_protected_last(tmp_path):
    ws, secret = tmp_path / "ws", tmp_path / "ws" / "secret"
    text = command_sandbox.profile([ws], [secret])
    lines = text.splitlines()
    assert lines[:3] == ["(version 1)", "(allow default)", '(deny file-write* (subpath "/"))']
    assert lines[3].startswith("(allow file-write* ") and json.dumps(str(ws.resolve())) in lines[3]
    assert lines[-1].startswith("(deny file-read* file-write* ") and json.dumps(str(secret.resolve())) in lines[-1]
    assert "network" not in text
    assert "(deny network*)" in command_sandbox.profile([ws], [secret], offline=True)


def test_folder_names_cannot_inject_rules(tmp_path):
    import re
    evil = tmp_path / 'a") (allow file-write* (subpath "/'
    text = command_sandbox.profile([evil], [])
    assert json.dumps(str(evil.resolve())) in text
    # Outside quoted strings there is still exactly one allow rule.
    bare = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    assert bare.count("(allow file-write*") == 1, bare


def test_protected_files_are_literal_and_folders_subpaths(tmp_path):
    f = tmp_path / "updater.key"
    f.write_text("k")
    text = command_sandbox.profile([], [f, tmp_path / "data"])
    assert f'(literal {json.dumps(str(f.resolve()))})' in text
    assert f'(subpath {json.dumps(str((tmp_path / "data").resolve()))})' in text


def test_macos_own_user_folder_is_writable_even_when_tmpdir_points_elsewhere(tmp_path, monkeypatch):
    """Xcode tools write caches under /var/folders/../T whatever $TMPDIR says."""
    import tempfile
    user = tmp_path / "var-folders" / "xk"
    (user / "T").mkdir(parents=True)
    elsewhere = tmp_path / "bench-tmp"
    elsewhere.mkdir()
    monkeypatch.setattr(command_sandbox.os, "confstr",
                        lambda name: str(user / "T") + "/" if name == 65537 else "")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(elsewhere))
    roots = command_sandbox.temp_roots()
    assert elsewhere.resolve() in roots and user.resolve() in roots
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(user / "T"))      # the usual case: same folder
    assert command_sandbox.temp_roots().count(user.resolve()) == 1

    def unsupported(name):
        raise ValueError("unrecognized configuration name")
    monkeypatch.setattr(command_sandbox.os, "confstr", unsupported)          # Linux: no such name
    assert command_sandbox.temp_roots()[0] == user.resolve()


def test_default_writable_and_protected_cover_the_plan(tmp_path):
    home = Path.home()
    writable = command_sandbox.default_writable(tmp_path)
    assert tmp_path.resolve() in writable and Path("/dev") in writable
    assert command_sandbox._real(home / "Library" / "Caches") in writable
    protected = command_sandbox.default_protected()
    for p in (home / ".ssh", home / "Library" / "Keychains", home / ".arslan-updater.key"):
        assert command_sandbox._real(p) in protected
    from server import config
    assert command_sandbox._real(config.data_dir()) in protected


@pytest.mark.parametrize("result,stopped", [
    ({"sandbox": "workspace", "ok": False, "exit_code": 1, "stderr": "zsh:1: operation not permitted: /x"}, True),
    ({"sandbox": "workspace", "ok": False, "exit_code": 1, "stdout": "PermissionError: [Errno 1] Operation not permitted"}, True),
    ({"sandbox": "workspace", "ok": False, "exit_code": 1, "stderr": "No such file or directory"}, False),
    ({"sandbox": "workspace", "ok": True, "exit_code": 0, "stderr": "operation not permitted"}, False),
    ({"sandbox": "off", "ok": False, "exit_code": 1, "stderr": "Operation not permitted"}, False),
    ({"sandbox": "workspace", "ok": False, "exit_code": None, "stderr": "Operation not permitted"}, False),
])
def test_what_counts_as_stopped_by_the_sandbox(result, stopped):
    assert command_sandbox.stopped_by_sandbox(result) is stopped


def test_the_conversation_grant_is_per_conversation_and_in_memory():
    command_sandbox.grant("c1")
    command_sandbox.grant(None)
    assert command_sandbox.granted("c1") and not command_sandbox.granted("c2") and not command_sandbox.granted(None)
    command_sandbox._reset_for_tests()
    assert not command_sandbox.granted("c1")


async def test_without_seatbelt_commands_run_as_before_and_say_so(tmp_path, monkeypatch):
    monkeypatch.setattr(command_sandbox, "wrapper", lambda *a, **k: None)
    out = await terminal_exec.run("echo hi", cwd=tmp_path, sandbox=True)
    assert out["ok"] is True and out["sandbox"] == "unavailable" and "not available" in out["sandbox_note"]
    off = await terminal_exec.run("echo hi", cwd=tmp_path)
    assert off["sandbox"] == "off" and "sandbox_note" not in off


async def test_the_executor_sandboxes_unless_the_setting_or_the_loop_says_otherwise(tmp_path, monkeypatch):
    """The model's own args never let a command out: only the loop's context variable."""
    from server.registry.executors import RunCommandExecutor
    from server.db import session as db_session
    from server.db.models import Setting
    from tests.server.test_workspace_tool_gate import _wire
    ws = tmp_path / "ws"
    ws.mkdir()
    await _wire(tmp_path, monkeypatch, workspace=str(ws))
    seen = []

    async def fake_run(command, *, cwd, timeout_s, offline=False, sandbox=False):
        seen.append(sandbox)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(cwd), "sandbox": "x"}
    monkeypatch.setattr(terminal_exec, "run", fake_run)
    ex = RunCommandExecutor()
    await ex.execute({"command": "ls", "outside_sandbox": True})
    token = terminal_exec.OUTSIDE_SANDBOX.set(True)
    try:
        await ex.execute({"command": "ls"})
    finally:
        terminal_exec.OUTSIDE_SANDBOX.reset(token)
    async with db_session.AsyncSessionLocal() as db:
        db.add(Setting(key="terminal_sandbox_enabled", value="false"))
        await db.commit()
    await ex.execute({"command": "ls"})
    assert seen == [True, False, False]


# ── what the kernel refuses (macOS) ───────────────────────────────────────────

@pytest.mark.macos
@macos
async def test_writes_outside_the_workspace_are_stopped_and_flagged(box):
    ws, outside, _ = box
    inside = await terminal_exec.run("echo hi > made.txt && cat made.txt", cwd=ws, sandbox=True)
    assert inside["ok"] is True and inside["stdout"].strip() == "hi" and inside["sandbox"] == "workspace"
    out = await terminal_exec.run(f"echo x > '{outside}/b.txt'", cwd=ws, sandbox=True)
    assert out["ok"] is False and out["sandbox_denied"] is True and "working folder" in out["note"]
    assert not (outside / "b.txt").exists()
    moved = await terminal_exec.run(f"touch '{outside}/c' 2>/dev/null; mv made.txt '{outside}/'", cwd=ws, sandbox=True)
    assert moved["sandbox_denied"] is True and (ws / "made.txt").exists()


@pytest.mark.macos
@macos
async def test_a_protected_folder_stays_closed_inside_a_writable_one(box):
    ws, _, secret = box
    read = await terminal_exec.run("cat secret/key", cwd=ws, sandbox=True)
    assert read["ok"] is False and "hush" not in read["stdout"] and read["sandbox_denied"] is True
    write = await terminal_exec.run("echo x > secret/new", cwd=ws, sandbox=True)
    assert write["sandbox_denied"] is True and not (secret / "new").exists()
    listing = await terminal_exec.run("ls secret", cwd=ws, sandbox=True)
    assert listing["ok"] is False and "key" not in listing["stdout"]


@pytest.mark.macos
@macos
async def test_the_keychain_folder_and_ssh_keys_cannot_be_read(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for folder in (Path.home() / "Library" / "Keychains", Path.home() / ".ssh"):
        if not folder.exists():
            continue                     # nothing to protect on this machine
        out = await terminal_exec.run(f"ls '{folder}'", cwd=ws, sandbox=True)
        assert out["ok"] is False and out["sandbox_denied"] is True, out
        assert out["stdout"] == ""


@pytest.mark.macos
@macos
async def test_temp_and_caches_stay_writable(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    out = await terminal_exec.run(
        "python3 -c \"import tempfile,os; p=tempfile.mktemp(); open(p,'w').write('t'); os.remove(p); print('ok')\"",
        cwd=ws, sandbox=True)
    assert out["ok"] is True and out["stdout"].strip() == "ok"


@pytest.mark.macos
@macos
async def test_offline_inside_the_sandbox_blocks_network_and_still_writes(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        out = await terminal_exec.run(
            f"python3 -c \"import socket; socket.create_connection(('127.0.0.1', {port}), 2)\" && echo connected",
            cwd=ws, sandbox=True, offline=True)
        assert out["ok"] is False and "connected" not in out["stdout"]
        made = await terminal_exec.run("echo a > a.txt", cwd=ws, sandbox=True, offline=True)
        assert made["ok"] is True and (ws / "a.txt").read_text() == "a\n"
    finally:
        srv.close()


@pytest.mark.macos
@macos
async def test_a_tool_that_brings_its_own_sandbox_is_seen_as_stopped(tmp_path):
    """sandbox-exec cannot nest; a command that starts its own must be offered a re-run outside."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = await terminal_exec.run("/usr/bin/sandbox-exec -p '(version 1)(allow default)' /usr/bin/true",
                                  cwd=ws, sandbox=True)
    assert out["ok"] is False and out["sandbox_denied"] is True
