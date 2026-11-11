"""HR-1 #813 review 11: the profile reaches sandbox-exec as a file (`-f`), not as an argument.

The commands wrapper, the outside floor's wrapper and the MCP preset write the profile to a new file
(`command_sandbox.write_profile`: O_CREAT | O_EXCL | O_NOFOLLOW, 0600, in Arslan's data folder, which every preset
closes) and remove it once the process has exited (a command) or has answered (an MCP server), on every path. A file
or a link already at the path fails the start, and a link there is never followed.

These run anywhere: sandbox-exec is stood in for by a script that checks it was given `-f` and a file, then runs the
rest of its argv (`fake_exec`). What the kernel does with a large profile is test_hr1_run_later_link_cap.py's.
Stand-in names and plain paths only.
"""
from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from server.services import capability_sandbox, command_sandbox, run_later, run_temp, terminal_exec

STAND_IN = "zz-stand-in-word"


@pytest.fixture
def fake_exec(tmp_path, monkeypatch):
    """sandbox-exec stood in for; the profile files written (path, mode, text) while each was being written."""
    exe = tmp_path / "bin" / "sandbox-exec"
    exe.parent.mkdir()
    exe.write_text('#!/bin/sh\n[ "$1" = -f ] || exit 97\n[ -f "$2" ] || exit 98\nshift 2\nexec "$@"\n')
    exe.chmod(0o755)
    monkeypatch.setattr(command_sandbox, "_SANDBOX_EXEC", str(exe))
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    written: list[tuple[Path, int, str]] = []
    real = command_sandbox.write_profile

    def recording(text):
        path = real(text)
        written.append((path, stat.S_IMODE(os.lstat(path).st_mode), path.read_text()))
        return path
    monkeypatch.setattr(command_sandbox, "write_profile", recording)
    return written


def _work(tmp_path) -> Path:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return work


async def _run(work, command, **kw):
    return await terminal_exec.run(command, cwd=work, sandbox=True, offline=True, **kw)


def test_the_file_is_made_new_0600_and_never_followed(monkeypatch, tmp_path):
    """O_CREAT | O_EXCL | O_NOFOLLOW, write-only, mode 0600; the text as given."""
    opened = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **kw):
        if Path(path).parent == command_sandbox.profile_folder():
            opened.append((flags, mode))
        return real_open(path, flags, mode, *a, **kw)
    monkeypatch.setattr(command_sandbox.os, "open", spy)
    path = command_sandbox.write_profile("(version 1)\n")
    try:
        (flags, mode), = opened
        for flag in (os.O_CREAT, os.O_EXCL, os.O_NOFOLLOW, os.O_WRONLY):
            assert flags & flag == flag, flag
        assert mode == 0o600 and stat.S_IMODE(os.lstat(path).st_mode) == 0o600
        assert path.read_text() == "(version 1)\n"
        assert stat.S_IMODE(os.lstat(path.parent).st_mode) == 0o700           # a folder of ours
    finally:
        command_sandbox.remove_profile(path)


@pytest.mark.parametrize("command,ok", [("true", True), ("exit 3", False)], ids=["success", "failure"])
async def test_a_commands_profile_file_is_gone_once_it_exits(fake_exec, tmp_path, command, ok):
    result = await _run(_work(tmp_path), command)
    assert result["ok"] is ok and result["sandbox"] == "workspace"
    (path, mode, text), = fake_exec
    assert mode == 0o600 and text.startswith("(version 1)\n(deny default)\n")
    assert not os.path.lexists(path)


async def test_the_floors_profile_file_is_gone_once_it_exits(fake_exec, tmp_path):
    result = await terminal_exec.run("true", cwd=_work(tmp_path), sandbox=False, offline=True, hold_run_later=True)
    assert result["ok"] and result["sandbox"] == "outside"
    (path, mode, _), = fake_exec
    assert mode == 0o600 and not os.path.lexists(path)


@pytest.fixture
def late_reap(monkeypatch):
    """asyncio reaps a child 0.3 s late (its watcher thread waits before `waitpid`), as on a loaded runner: a killed
    process stays a zombie, still alive to `killpg(0)`, for that long. Returns the run temp folders there now."""
    import threading
    import time
    real = os.waitpid

    def late(pid, options):
        if threading.current_thread() is not threading.main_thread():
            time.sleep(0.3)
        return real(pid, options)
    monkeypatch.setattr(os, "waitpid", late)
    return _run_temps()


def _run_temps() -> set[str]:
    base = run_temp.root()
    return set(os.listdir(base)) if base.is_dir() else set()


async def test_the_file_is_gone_after_a_time_limit(fake_exec, late_reap, tmp_path):
    """The killed process is reaped before the command returns, so the run's temp folder went with it (SBX-3 §1a,
    #813 review 12: a folder left here was swept by a later test)."""
    result = await _run(_work(tmp_path), "sleep 30", timeout_s=0.5)
    assert result["code"] == "time_limit"
    (path, _, _), = fake_exec
    assert not os.path.lexists(path)
    assert _run_temps() == late_reap


async def test_the_file_is_gone_after_a_cancel(fake_exec, late_reap, tmp_path):
    """The same after a cancel: the cancel waits for the reap (`terminal_exec._reap_then_cancel`), and then the run's
    temp folder goes."""
    task = asyncio.ensure_future(_run(_work(tmp_path), "sleep 30"))
    for _ in range(200):
        if fake_exec:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.2)                       # started
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (path, _, _), = fake_exec
    assert not os.path.lexists(path)
    assert _run_temps() == late_reap


async def test_the_file_is_gone_after_a_failed_start(fake_exec, tmp_path):
    """The stand-in can't be executed: the start fails (exec error) and the file goes all the same."""
    Path(command_sandbox._SANDBOX_EXEC).chmod(0o644)
    with pytest.raises(OSError):
        await _run(_work(tmp_path), "true")
    (path, _, _), = fake_exec
    assert not os.path.lexists(path)


async def test_a_file_cancelled_while_it_is_written_is_removed_when_the_writing_ends(tmp_path):
    """`in_thread`, the cancel path while the wrapper still runs: the thread finishes and its file goes then."""
    gate, paths = asyncio.Event(), []
    loop = asyncio.get_running_loop()

    def build():
        path = command_sandbox.write_profile("(version 1)\n")
        paths.append(path)
        loop.call_soon_threadsafe(gate.set)
        import time
        time.sleep(0.3)
        return [command_sandbox._SANDBOX_EXEC, "-f", str(path)]
    task = asyncio.ensure_future(command_sandbox.in_thread(build))
    await gate.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(100):
        if not os.path.lexists(paths[0]):
            break
        await asyncio.sleep(0.02)
    assert not os.path.lexists(paths[0])


@pytest.mark.parametrize("planted", ["file", "link", "dangling-link"])
async def test_something_already_at_the_path_fails_the_start_and_is_not_followed(fake_exec, monkeypatch, tmp_path,
                                                                                 planted):
    """A file, a link to a file, or a link to a path that doesn't exist, already where the profile goes: the start
    fails (FileExistsError, O_EXCL), nothing runs, the link's target is neither written nor made."""
    monkeypatch.setattr(command_sandbox, "_profile_name", lambda: f"{STAND_IN}.sb")
    at = command_sandbox.profile_folder() / f"{STAND_IN}.sb"
    victim = tmp_path / f"{STAND_IN}-victim.txt"
    if planted == "file":
        at.write_text("(version 1)\n(allow default)\n")
    else:
        if planted == "link":
            victim.write_text("old")
        at.symlink_to(victim)
    work = _work(tmp_path)
    try:
        with pytest.raises(FileExistsError):
            await _run(work, f"touch {STAND_IN}-ran")
        assert not (work / f"{STAND_IN}-ran").exists() and fake_exec == []
        if planted == "file":
            assert at.read_text() == "(version 1)\n(allow default)\n"
        elif planted == "link":
            assert victim.read_text() == "old"
        else:
            assert not os.path.lexists(victim)
        with pytest.raises(FileExistsError):                              # the MCP preset the same way
            capability_sandbox.wrap("/bin/echo", [], {"PATH": "/usr/bin"},
                                    {"root": str(tmp_path / "srv"), "folders": [], "network": False})
    finally:
        at.unlink()


def test_the_mcp_preset_starts_from_a_file_and_names_it_in_its_args(tmp_path):
    command, args, _, _ = capability_sandbox.wrap("/bin/echo", ["hi"], {"PATH": "/usr/bin"},
                                                  {"root": str(tmp_path / "srv"), "folders": [], "network": False})
    path = command_sandbox.profile_path(args)
    try:
        assert command == capability_sandbox.SANDBOX_EXEC and args[0] == "-f" and args[2:] == ["/bin/echo", "hi"]
        assert path.parent == command_sandbox.profile_folder() and stat.S_IMODE(os.lstat(path).st_mode) == 0o600
        assert not path.is_relative_to(tmp_path / "srv")              # never in the server's own folders
    finally:
        command_sandbox.remove_profile(path)


@pytest.mark.parametrize("answers", [True, False], ids=["answered", "failed-start"])
async def test_the_session_removes_an_mcp_servers_profile_once_it_answers_or_fails(monkeypatch, tmp_path, answers):
    """While the server starts, the file is there; once it has answered `initialize` it is gone (the session still
    open); when the start fails it goes with the session's stack."""
    import contextlib

    import mcp
    import mcp.client.stdio
    from server.mcp import proxy_resolve, session
    seen = {}

    @contextlib.asynccontextmanager
    async def stdio_client(params, errlog=None):
        path = command_sandbox.profile_path(params.args)
        seen["at_start"] = path is not None and path.exists()
        seen["path"] = path
        yield None, None

    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def initialize(self):
            if not answers:
                raise ConnectionError("closed")
    monkeypatch.setattr(mcp.client.stdio, "stdio_client", stdio_client)
    monkeypatch.setattr(mcp, "ClientSession", Client)
    monkeypatch.setattr(proxy_resolve, "_scutil_proxy", dict)
    server = {"id": 7, "command": "/bin/echo", "args": [], "env": {"PATH": "/usr/bin"},
              "sandbox": {"root": str(tmp_path / "srv"), "folders": [], "network": False}}
    manager = session.MCPSessionManager()
    if answers:
        _, stack = await manager._open_session(server)
        assert seen["at_start"] and not seen["path"].exists()
        await stack.aclose()
    else:
        with pytest.raises(ConnectionError):
            await manager._open_session(server)
        assert seen["at_start"] and not seen["path"].exists()


async def test_past_the_link_cap_a_command_doesnt_start_and_is_told_why(monkeypatch, tmp_path):
    """The stop note, from the product path, in the sandbox and under the floor that holds the run-later files."""
    def too_many(*a, **kw):
        raise run_later.TooManyLinks(run_later.WALK_LINKS)
    monkeypatch.setattr(command_sandbox, "wrapper", too_many)
    monkeypatch.setattr(command_sandbox, "outside_wrapper", too_many)
    work = _work(tmp_path)
    for result in (await _run(work, f"touch {STAND_IN}-ran"),
                   await terminal_exec.run(f"touch {STAND_IN}-ran", cwd=work, offline=True, hold_run_later=True)):
        assert result["ok"] is False and result["exit_code"] is None and result["code"] == "too_many_links"
        assert f"more than {run_later.WALK_LINKS:,} links" in result["note"] and str(work) in result["note"]
        assert not (work / f"{STAND_IN}-ran").exists()
