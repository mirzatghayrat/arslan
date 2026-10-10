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
    assert lines[-2].startswith("(deny file-read* file-write* ") and json.dumps(str(secret.resolve())) in lines[-2]
    # The protected paths are closed to sockets too; TCP and everything else stay open.
    assert lines[-1] == lines[-2].replace("(deny file-read* file-write* ", "(deny network-outbound ", 1)
    assert [line for line in lines if "network" in line] == [lines[-1]]
    assert "(deny network*)" in command_sandbox.profile([ws], [secret], offline=True)
    assert "network" not in command_sandbox.profile([ws], [])


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
    from server.services import hands_client
    assert command_sandbox._real(hands_client.folder()) in protected


def test_hands_folder_comes_from_the_account_not_from_home(monkeypatch, tmp_path):
    """Hands derives its folder from getpwuid; so must Arslan, or a redirected
    $HOME would protect one folder while Hands listens in another."""
    from server.services import hands_client
    before = hands_client.folder()
    monkeypatch.setenv("HOME", str(tmp_path))
    assert hands_client.folder() == before
    assert before.parts[-3:] == ("Library", "Application Support", "Arslan Hands")


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

    async def fake_run(command, *, cwd, timeout_s, offline=False, sandbox=False, **kw):
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


@pytest.mark.macos
@macos
async def test_a_socket_in_a_protected_folder_cannot_be_reached(monkeypatch):
    """Measured 2026-10-03: the file rule alone lets connect() through; the
    network-outbound rule is what closes Arslan Hands' socket to commands."""
    import os
    import tempfile
    import threading
    short = Path(tempfile.mkdtemp(prefix="ahs", dir="/tmp")).resolve()   # AF_UNIX paths are short
    ws = short / "ws"
    ws.mkdir()
    folder = short / "hands"
    folder.mkdir(mode=0o700)
    path = folder / "s.sock"
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    os.chmod(path, 0o600)
    srv.listen(4)

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            conn.sendall(b"hello")
            conn.close()
    threading.Thread(target=serve, daemon=True).start()
    probe = (f"python3 -c \"import socket; s=socket.socket(socket.AF_UNIX); s.connect('{path}'); "
             f"print('GOT', s.recv(5))\"")
    try:
        monkeypatch.setattr(command_sandbox, "default_protected", lambda: [folder])
        out = await terminal_exec.run(probe, cwd=ws, sandbox=True)
        assert out["ok"] is False and "GOT" not in out["stdout"] and out["sandbox_denied"] is True, out
        token = await terminal_exec.run(f"cat '{folder}/s.sock'", cwd=ws, sandbox=True)
        assert token["ok"] is False
        monkeypatch.setattr(command_sandbox, "default_protected", lambda: [])
        control = await terminal_exec.run(probe, cwd=ws, sandbox=True)
        assert control["ok"] is True and "GOT b'hello'" in control["stdout"], "the probe itself works"
    finally:
        srv.close()
        path.unlink(missing_ok=True)
        folder.rmdir()
        ws.rmdir()
        short.rmdir()


# ── 0.1.59: "Desktop, Documents, Downloads: Off" closes them to commands too ──

@pytest.fixture
def green(tmp_path):
    """Stand-ins for the user's Documents and Downloads (never the real ones): a working folder
    and a project kept inside them, a private file beside each, and a symlink pointing in."""
    docs, downs = tmp_path / "Home" / "Documents", tmp_path / "Home" / "Downloads"
    ws, project = docs / "Arslan", downs / "Pocket Garden"
    for folder in (ws, project):
        folder.mkdir(parents=True)
    (docs / "taxes.txt").write_text("private")
    (downs / "bank.pdf").write_text("private")
    (ws / "notes.md").write_text("work")
    (project / "plan.md").write_text("plan")
    (tmp_path / "link").symlink_to(downs)
    return {"closed": [docs, downs], "readable": [project], "ws": ws, "project": project,
            "docs": docs, "downs": downs, "link": tmp_path / "link"}


@pytest.mark.macos
@macos
async def test_closed_folders_cannot_be_opened_by_a_command(green):
    g = green
    run = lambda cmd: terminal_exec.run(cmd, cwd=g["ws"], sandbox=True, closed=g["closed"], readable=g["readable"])  # noqa: E731
    for cmd in (f"cat '{g['docs']}/taxes.txt'", f"ls '{g['downs']}'", f"find '{g['downs']}' -type f",
                f"cat '/System/Volumes/Data{command_sandbox._real(g['downs'])}/bank.pdf'",
                f"cat '{g['link']}/bank.pdf'"):
        out = await run(cmd)
        assert out["ok"] is False and "private" not in out["stdout"] and "bank.pdf" not in out["stdout"], cmd
        assert out["sandbox_denied"] is True and "closed" in out["note"], cmd
    # The working folder and the project kept inside them stay open (the project read-only).
    both = await run("cat notes.md && echo more > more.md")
    assert both["ok"] is True and both["stdout"] == "work" and (g["ws"] / "more.md").read_text().strip() == "more"
    assert (await run(f"cat '{g['project']}/plan.md'"))["stdout"].strip() == "plan"
    write = await run(f"echo x > '{g['project']}/new.md'")
    assert write["ok"] is False and not (g["project"] / "new.md").exists()


@pytest.mark.macos
@macos
async def test_with_the_folders_on_nothing_changes(green):
    g = green
    out = await terminal_exec.run(f"cat '{g['docs']}/taxes.txt'", cwd=g["ws"], sandbox=True)
    assert out["ok"] is True and out["stdout"].strip() == "private"


async def test_the_executor_closes_the_folders_only_while_the_setting_is_off(tmp_path, monkeypatch):
    from server.registry import executors
    from server.registry.executors import RunCommandExecutor
    from server.db import session as db_session
    from server.db.models import Setting
    from server.services import workspace_paths
    from tests.server.test_workspace_tool_gate import _wire
    ws, docs, project = tmp_path / "ws", tmp_path / "Documents", tmp_path / "Documents" / "Garden"
    for folder in (ws, project):
        folder.mkdir(parents=True)
    await _wire(tmp_path, monkeypatch, workspace=str(ws))
    monkeypatch.setattr(workspace_paths, "green_roots", lambda: [docs])

    async def projects():
        return [project]
    monkeypatch.setattr(executors, "_project_folders", projects)
    seen = []

    async def fake_run(command, *, cwd, timeout_s, offline=False, sandbox=False, closed=(), readable=()):
        seen.append((list(closed), list(readable)))
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(cwd), "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "run", fake_run)
    await RunCommandExecutor().execute({"command": "ls"})
    async with db_session.AsyncSessionLocal() as db:
        db.add(Setting(key="default_read_enabled", value="false"))
        await db.commit()
    await RunCommandExecutor().execute({"command": "ls"})
    assert seen == [([], []), ([docs], [project])]


def test_the_profile_closes_then_reopens_then_protects(tmp_path):
    docs, ws, project, key = tmp_path / "Documents", tmp_path / "Documents" / "ws", tmp_path / "Documents" / "P", tmp_path / "k"
    text = command_sandbox.profile([ws], [key], closed=[docs], readable=[project])
    lines = text.splitlines()
    closing = next(i for i, line in enumerate(lines) if line.startswith("(deny file-read* file-write*") and "Documents\"" in line)
    reopen_rw = next(i for i, line in enumerate(lines) if line.startswith("(allow file-read* file-write*"))
    reopen_r = next(i for i, line in enumerate(lines) if line.startswith("(allow file-read* ") and "file-write" not in line)
    protect = next(i for i, line in enumerate(lines) if json.dumps(str(command_sandbox._real(key))) in line and "deny" in line)
    assert closing < reopen_rw < protect and closing < reopen_r < protect
    assert json.dumps(str(command_sandbox._real(ws))) in lines[reopen_rw]
    assert json.dumps(str(command_sandbox._real(project))) in lines[reopen_r]
    # The setting on: not a single extra rule.
    assert command_sandbox.profile([ws], [key]) == command_sandbox.profile([ws], [key], closed=[], readable=[project])


def test_a_stopped_command_is_told_which_folders_the_user_keeps_closed():
    home = Path.home()
    note = command_sandbox.note(home / "Arslan", [home / "Downloads", home / "Documents"])
    assert "~/Downloads, ~/Documents" in note and "outside_sandbox" in note
    assert "closed" not in command_sandbox.note(home / "Arslan")
