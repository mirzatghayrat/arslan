"""SMART-1 (v0.1.64): run_command sees the user's interactive PATH, including what ~/.zshrc adds.

A zsh login shell (`-l`) reads ~/.zprofile but never ~/.zshrc, where many tools add their folder (`~/.local/bin`,
where `claude` lives). So the PATH is read once per server start from an interactive login shell, OUTSIDE any
sandbox, taking only a line framed by a per-call random marker, with a hard time limit for the whole process
group; the commands run later never run the rc files themselves.
"""
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from server.mcp import spawn_env
from server.services import terminal_exec

# Real-shell tests carry the macos marker, so macOS CI runs them (zsh is the Mac's shell; Linux has none).
zsh = pytest.mark.skipif(sys.platform != "darwin" or shutil.which("zsh") is None, reason="macOS zsh")


@pytest.fixture(autouse=True)
def _fresh_cache():
    cached = spawn_env.login_shell_path
    cached.cache_clear()
    yield
    cached.cache_clear()


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", shutil.which("zsh") or "/bin/zsh")
    monkeypatch.delenv("ZDOTDIR", raising=False)
    return home


def _tool(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("#!/bin/sh\necho found-it\n")
    (folder / name).chmod(0o755)


@pytest.mark.macos
@zsh
async def test_a_tool_only_zshrc_puts_on_path_is_found_by_run_command(home, tmp_path):
    _tool(home / "tools", "smart1tool")
    (home / ".zshrc").write_text('export PATH="$HOME/tools:$PATH"\n')
    assert str(home / "tools") in spawn_env.login_shell_path().split(os.pathsep)
    result = await terminal_exec.run("smart1tool", cwd=tmp_path, unwrapped=True)
    assert result["ok"] and result["stdout"].strip() == "found-it", result


@pytest.mark.macos
@zsh
@pytest.mark.parametrize("rc", [
    # Fake markers, one of them the shape a fixed (empty) token would have: only this call's random one counts.
    'echo "hello from rc"; printf "__ARSLAN_PATH__/evil__END__\\n__ARSLAN_PATH___/evil__END___\\n"\n'
    'export PATH="$HOME/tools:$PATH"\n',
    'read -r answer\nexport PATH="$HOME/tools:$PATH"\n',
])
def test_rc_output_and_prompts_dont_break_or_spoof_it(home, rc):
    (home / ".zshrc").write_text(rc)
    path = spawn_env.login_shell_path().split(os.pathsep)
    assert str(home / "tools") in path and "/evil" not in path


@pytest.mark.macos
@zsh
def test_an_rc_that_hangs_is_cut_off_at_the_limit(home, monkeypatch):
    monkeypatch.setattr(spawn_env, "_SHELL_TIMEOUT", 1.0)
    (home / ".zshrc").write_text("sleep 30 &\nsleep 30\n")      # a child that keeps the pipes open, too
    start = time.monotonic()
    assert spawn_env.login_shell_path() == ""
    assert time.monotonic() - start < 4


def test_the_usual_user_bin_folders_are_fallbacks(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: "")
    path = spawn_env.merged_path().split(os.pathsep)
    for sub in (".local/bin", "bin", ".cargo/bin"):
        assert str(tmp_path / sub) in path, sub


@pytest.mark.macos
@zsh
def test_a_hung_rc_leaves_no_process_behind(home, monkeypatch):
    """The whole process group is killed at the limit, a background child of the rc included."""
    import subprocess
    monkeypatch.setattr(spawn_env, "_SHELL_TIMEOUT", 1.0)
    (home / ".zshrc").write_text("sleep 30 &\nsleep 30\n")
    started = []
    real = subprocess.Popen

    def recording(*a, **k):
        started.append(real(*a, **k))
        return started[-1]
    monkeypatch.setattr(spawn_env.subprocess, "Popen", recording)
    assert spawn_env.login_shell_path() == ""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.killpg(started[0].pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail("a process of the rc's group is still running")


@pytest.mark.macos
@zsh
def test_the_shell_gets_an_empty_stdin_whatever_the_servers_is(home, monkeypatch):
    """A prompt in an rc reads EOF at once, even when the server's own stdin is an open pipe (the sidecar)."""
    monkeypatch.setattr(spawn_env, "_SHELL_TIMEOUT", 2.0)
    (home / ".zshrc").write_text('read -r answer\nexport PATH="$HOME/tools:$PATH"\n')
    saved = os.dup(0)
    r, w = os.pipe()
    os.dup2(r, 0)
    try:
        path = spawn_env.login_shell_path().split(os.pathsep)
    finally:
        os.dup2(saved, 0)
        for fd in (saved, r, w):
            os.close(fd)
    assert str(home / "tools") in path


def test_only_a_whole_marker_line_counts(monkeypatch):
    class Shell:
        def __init__(self, argv, **kwargs):
            body = argv[-1].split('"', 2)[1]
            start, end = (part.replace("\\n", "") for part in body.split("%s"))
            self.pid = 0
            self.out = f"noise {start}/evil{end} trailing\n{start}/real/bin{end}\n"

        def communicate(self, timeout=None):
            return self.out, ""
    monkeypatch.setattr(spawn_env.subprocess, "Popen", Shell)
    assert spawn_env.login_shell_path() == "/real/bin"

