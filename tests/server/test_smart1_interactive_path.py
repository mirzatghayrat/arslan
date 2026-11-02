"""SMART-1 (v0.1.64): run_command sees the user's interactive PATH, including what ~/.zshrc adds.

A zsh login shell (`-l`) reads ~/.zprofile but never ~/.zshrc, where many tools add their folder (`~/.local/bin`,
where `claude` lives). So the PATH is read once per server start from an interactive login shell, OUTSIDE any
sandbox and with a minimal environment, taking only a line framed by a per-call random marker, with a hard time
limit for the whole process group, and falling back to `-l` alone when that gives nothing. The commands run later
read neither ~/.zshrc nor ~/.zprofile (`zsh -c` still reads ~/.zshenv, as it always has).
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
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)   # forwarded to the shell; a system rc may derive ZDOTDIR
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
def test_an_rc_that_hangs_is_cut_off_and_zprofile_still_counts(home, monkeypatch):
    """`-i -l` is cut off at the limit; `-l` alone then still gives what ~/.zprofile adds."""
    monkeypatch.setattr(spawn_env, "_SHELL_TIMEOUT", 1.0)
    (home / ".zprofile").write_text('export PATH="$HOME/zp:$PATH"\n')
    (home / ".zshrc").write_text('export PATH="$HOME/tools:$PATH"\nsleep 30 &\nsleep 30\n')
    start = time.monotonic()
    path = spawn_env.login_shell_path().split(os.pathsep)
    assert time.monotonic() - start < 4
    assert str(home / "zp") in path and str(home / "tools") not in path


@pytest.mark.macos
@zsh
def test_a_path_printed_before_a_child_holds_the_pipe_still_counts(home, monkeypatch):
    """The rc finishes and the PATH is printed, but a background child keeps the pipe open past the limit: the
    PATH read before the kill is used (only ~/.zshrc adds `tools`, so the `-l` fallback can't be what found it)."""
    monkeypatch.setattr(spawn_env, "_SHELL_TIMEOUT", 1.0)
    (home / ".zshrc").write_text('export PATH="$HOME/tools:$PATH"\n( trap "" HUP; sleep 30 ) &\n')
    start = time.monotonic()
    path = spawn_env.login_shell_path().split(os.pathsep)
    assert str(home / "tools") in path
    assert time.monotonic() - start >= 1.0      # it really was cut off at the limit


def test_the_usual_user_bin_folders_are_fallbacks(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: "")
    path = spawn_env.merged_path().split(os.pathsep)
    for sub in (".local/bin", "bin", ".cargo/bin"):
        assert str(tmp_path / sub) in path, sub


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:      # EPERM: a zombie not yet reaped, or the pid reused by another user; not gone yet
        return False
    return False


@pytest.mark.macos
@zsh
def test_a_hung_rc_leaves_no_process_behind(home, monkeypatch):
    """The whole process group is killed at the limit with SIGKILL: the shell and the rc's background child, both
    ignoring SIGTERM, are gone."""
    monkeypatch.setattr(spawn_env, "_SHELL_TIMEOUT", 1.0)
    pids = home / "pids"
    (home / ".zshrc").write_text(f"trap '' TERM\necho $$ > {pids}\nsleep 30 &\necho $! >> {pids}\nsleep 30\n")
    spawn_env.login_shell_path()
    started = [int(x) for x in pids.read_text().split()]
    assert len(started) == 2
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not all(_gone(pid) for pid in started):
            time.sleep(0.05)
        assert all(_gone(pid) for pid in started), f"still running: {[p for p in started if not _gone(p)]}"
    finally:
        for pid in started:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


@pytest.mark.macos
@zsh
def test_the_rc_sees_a_minimal_environment(home, monkeypatch):
    """The server's secrets never reach the rc files; the flag that lets an rc skip slow steps does."""
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "smart1-secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "smart1-provider-key")
    seen = home / "seen"
    (home / ".zshrc").write_text(f"env > {seen}\n")
    spawn_env.login_shell_path()
    text = seen.read_text()
    assert "smart1-secret-value" not in text and "smart1-provider-key" not in text
    assert "ARSLAN_RESOLVING_ENVIRONMENT=1" in text.splitlines()
    assert f"HOME={home}" in text.splitlines()


@pytest.mark.macos
@zsh
async def test_a_dot_on_the_rc_path_doesnt_let_a_planted_tool_run(home, tmp_path):
    """An rc that puts `.` on PATH: a file of that name in the command's folder is not found."""
    (home / ".zshrc").write_text('export PATH=".:$PATH"\n')
    assert "." in spawn_env.login_shell_path().split(os.pathsep)      # the shell really gave it
    work = tmp_path / "work"
    _tool(work, "smart1planted")
    result = await terminal_exec.run("smart1planted", cwd=work, unwrapped=True)
    assert "found-it" not in result["stdout"], result


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



def test_only_absolute_folders_reach_the_merged_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f".{os.pathsep}/usr/bin{os.pathsep}rel/bin")
    monkeypatch.setattr(spawn_env, "login_shell_path",
                        lambda: os.pathsep.join([".", "", "bin", "./x", "/nul\0x", "/opt/real"]))
    path = spawn_env.merged_path().split(os.pathsep)
    assert path[:2] == ["/usr/bin", "/opt/real"]
    assert all(os.path.isabs(p) and "\0" not in p for p in path), path


def test_an_interactive_shell_with_no_answer_falls_back_to_a_login_shell(monkeypatch):
    """Without a real zsh: the first try (`-i -l`) prints no marker, the second (`-l`) does; both get the minimal
    environment."""
    monkeypatch.setenv("OPENAI_API_KEY", "smart1-provider-key")
    calls = []

    class Shell:
        def __init__(self, argv, **kwargs):
            calls.append((argv[1:-2], kwargs["env"]))
            body = argv[-1].split('"', 2)[1]
            start, end = (part.replace("\\n", "") for part in body.split("%s"))
            self.pid = 0
            self.out = "" if "-i" in argv else f"{start}/login/bin{end}\n"

        def communicate(self, timeout=None):
            return self.out, ""
    monkeypatch.setattr(spawn_env.subprocess, "Popen", Shell)
    assert spawn_env.login_shell_path() == "/login/bin"
    assert [flags for flags, _ in calls] == [["-i", "-l"], ["-l"]]
    for _, env in calls:
        assert "OPENAI_API_KEY" not in env and env["ARSLAN_RESOLVING_ENVIRONMENT"] == "1"


@pytest.mark.macos
@zsh
def test_a_path_printed_before_a_child_that_left_the_group_holds_the_pipe_still_counts(home, monkeypatch):
    """A child in its own session isn't killed with the shell's group and keeps the pipe past the second wait:
    what was read before still counts (#674 review, M5c)."""
    monkeypatch.setattr(spawn_env, "_SHELL_TIMEOUT", 1.0)
    pids = home / "pids"
    (home / ".zshrc").write_text(
        'export PATH="$HOME/tools:$PATH"\n'
        f"/usr/bin/perl -MPOSIX -e 'POSIX::setsid(); sleep 30' &\necho $! > {pids}\n")
    try:
        path = spawn_env.login_shell_path().split(os.pathsep)
        assert str(home / "tools") in path
    finally:
        for pid in (pids.read_text().split() if pids.exists() else []):
            try:
                os.kill(int(pid), 9)
            except OSError:
                pass


def test_overlapping_first_calls_read_the_shell_once(monkeypatch):
    """The prewarm, a command and the turn's environment note can ask at the same time (#674 review)."""
    import threading
    reads = []

    def shell(argv, env):
        reads.append(argv)
        time.sleep(0.3)
        body = argv[-1].split('"', 2)[1]
        start, end = (part.replace("\\n", "") for part in body.split("%s"))
        return f"{start}/once/bin{end}\n"
    monkeypatch.setattr(spawn_env, "_shell_output", shell)
    seen = []
    threads = [threading.Thread(target=lambda: seen.append(spawn_env.login_shell_path())) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == ["/once/bin"] * 3 and len(reads) == 1


# ── nothing on the event loop waits for the shell (#674 review) ─────────────

async def _longest_stall(coro) -> float:
    import asyncio
    gaps: list[float] = []
    done = False

    async def tick():
        last = time.monotonic()
        while not done:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now
    ticker = asyncio.create_task(tick())
    await asyncio.sleep(0.03)
    try:
        await coro
    except Exception:  # noqa: BLE001 — only the loop's wait is measured here; a refusal after it is expected
        pass
    finally:
        done = True
        await ticker
    return max(gaps)


@pytest.fixture
def slow_path(monkeypatch):
    """The browser status, the user's PATH and node's lookup take 0.6 s, as a slow ~/.zshrc does before the cache."""
    from server.services import managed_browser

    def slow_status():
        time.sleep(0.6)
        return {"ready": False, "reason": "node_required", "version": "x"}

    def slow_resolve(command):
        time.sleep(0.6)
        return "/usr/bin/true"
    monkeypatch.setattr(managed_browser, "status", slow_status)
    monkeypatch.setattr(spawn_env, "resolve_command", slow_resolve)


async def test_the_capability_rows_and_the_tool_list_never_wait_on_the_loop(tmp_path, monkeypatch, slow_path):
    from server.orchestrator import arslan
    from server.services import capability_list
    from tests.server.test_workspace_tool_gate import _wire
    await _wire(tmp_path, monkeypatch, workspace=str(tmp_path))
    assert await _longest_stall(capability_list._builtin_rows()) < 0.3
    assert await _longest_stall(arslan._arslan_tools()) < 0.3


async def test_starting_a_browser_never_waits_on_the_loop(slow_path):
    from server.services import agent_browser, browser_reader, managed_browser
    import asyncio
    assert await _longest_stall(browser_reader.ReaderSession("c1", None).start()) < 0.3
    assert await _longest_stall(agent_browser._Worker()._run(asyncio.get_running_loop().create_future())) < 0.3
    assert await _longest_stall(managed_browser.setup()) < 0.3
    assert await _longest_stall(managed_browser._preview("https://example.com")) < 0.3


def test_no_async_code_calls_the_path_helpers_directly():
    """Source pin: in an `async def`, the helpers that may wait for the login shell run in a thread
    (`await asyncio.to_thread(...)`), never called on the loop."""
    import ast
    owners = {"managed_browser": {"status"}, "spawn_env": {"resolve_command", "merged_path", "login_shell_path"},
              "agent_browser": {"available"}}
    bare = {"merged_path", "login_shell_path", "resolve_command"}
    root = Path(__file__).resolve().parents[2] / "server"
    hits = []
    for path in root.rglob("*.py"):
        for fn in ast.walk(ast.parse(path.read_text())):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            stack = list(fn.body)
            while stack:
                node = stack.pop()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                    continue
                if isinstance(node, ast.Call):
                    f = node.func
                    if ((isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                         and f.attr in owners.get(f.value.id, ())) or (isinstance(f, ast.Name) and f.id in bare)):
                        hits.append(f"{path.relative_to(root)}:{node.lineno}")
                stack.extend(ast.iter_child_nodes(node))
    assert hits == []
