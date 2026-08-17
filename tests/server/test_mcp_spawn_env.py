"""spawn_env — PATH resolution for stdio MCP spawns in the packaged app.

A Finder-launched .app inherits LaunchServices' minimal PATH
(/usr/bin:/bin:/usr/sbin:/sbin), so `npx` from Homebrew/nvm is invisible and
every stdio server dies with [Errno 2]. Dev runs inherit the terminal PATH and
never reproduce it. These tests pin the resolution contract: login-shell PATH
fetched once, merged after the current PATH, hard fallbacks last, commands
resolved to absolute paths, and a missing command failing with an actionable
message instead of a bare Errno 2.
"""
import os
import subprocess

import pytest

from server.mcp import spawn_env


@pytest.fixture(autouse=True)
def _fresh_cache():
    spawn_env.login_shell_path.cache_clear()
    yield
    spawn_env.login_shell_path.cache_clear()


def test_login_shell_path_is_fetched_once_then_cached(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="/opt/homebrew/bin:/usr/bin", stderr="")

    monkeypatch.setattr(spawn_env.subprocess, "run", fake_run)
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert spawn_env.login_shell_path() == "/opt/homebrew/bin:/usr/bin"
    assert spawn_env.login_shell_path() == "/opt/homebrew/bin:/usr/bin"
    assert len(calls) == 1                       # cached — one shell spawn per process
    assert calls[0][0] == "/bin/zsh" and "-l" in calls[0]   # the LOGIN shell, not a bare subshell


def test_login_shell_failure_yields_empty_not_raise(monkeypatch):
    def boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr(spawn_env.subprocess, "run", boom)
    assert spawn_env.login_shell_path() == ""


def test_merged_path_orders_current_then_login_then_fallbacks(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: "/nvm/bin:/usr/bin")
    parts = spawn_env.merged_path().split(os.pathsep)
    # current PATH first (dev behaviour unchanged), login additions after, fallbacks last, no dupes
    assert parts[:2] == ["/usr/bin", "/bin"]
    assert parts[2] == "/nvm/bin"
    assert parts.count("/usr/bin") == 1
    for fb in ("/opt/homebrew/bin", "/usr/local/bin"):
        assert fb in parts


def test_merged_path_survives_shell_resolution_failure(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: "")
    parts = spawn_env.merged_path().split(os.pathsep)
    assert "/opt/homebrew/bin" in parts          # hard fallbacks still cover Homebrew


def test_resolve_command_finds_binary_via_merged_path(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    npx = fake_bin / "npx"
    npx.write_text("#!/bin/sh\n")
    npx.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")             # minimal LaunchServices PATH
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: str(fake_bin))
    assert spawn_env.resolve_command("npx") == str(npx)


def test_resolve_command_missing_raises_actionable_message(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))               # nothing here
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: "")
    # The dev machine's real /opt/homebrew/bin DOES hold npx — neutralize the
    # hard fallbacks so this tests the miss, not the host.
    monkeypatch.setattr(spawn_env, "_FALLBACK_DIRS", ())
    with pytest.raises(FileNotFoundError) as exc:
        spawn_env.resolve_command("npx")
    msg = str(exc.value)
    assert "npx" in msg and "PATH" in msg                   # names the command, names the cause
    assert "No such file or directory" not in msg           # not the bare Errno 2 the user saw


def test_resolve_command_leaves_explicit_paths_alone(monkeypatch):
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: "")
    assert spawn_env.resolve_command("/usr/bin/env") == "/usr/bin/env"


async def test_stdio_spawn_uses_resolved_command_and_merged_path(tmp_path, monkeypatch):
    """Through _open_session: the child gets an absolute command AND a PATH that
    contains the login-shell dirs — npx itself needs to find node."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    npx = fake_bin / "npx"
    npx.write_text("#!/bin/sh\n")
    npx.chmod(0o755)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: str(fake_bin))

    captured = {}

    class _FakeStdio:
        def __init__(self, params):
            captured["params"] = params

        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, *a):
            return False

    class _FakeSession:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def initialize(self):
            pass

    import mcp
    import mcp.client.stdio as stdio_mod
    monkeypatch.setattr(stdio_mod, "stdio_client", _FakeStdio)
    monkeypatch.setattr(mcp, "ClientSession", _FakeSession)

    from server.mcp.session import MCPSessionManager
    mgr = MCPSessionManager()
    _client, stack = await mgr._open_session(
        {"id": 1, "transport": "stdio", "command": "npx", "args": ["-y", "x"], "env": {}}
    )
    await stack.aclose()

    params = captured["params"]
    assert params.command == str(npx)
    assert str(fake_bin) in params.env["PATH"].split(os.pathsep)


async def test_stdio_spawn_explicit_env_path_wins(tmp_path, monkeypatch):
    """A PATH the user configured on the server row must not be second-guessed."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    tool = fake_bin / "mytool"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(spawn_env, "login_shell_path", lambda: "")

    captured = {}

    class _FakeStdio:
        def __init__(self, params):
            captured["params"] = params

        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, *a):
            return False

    class _FakeSession:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def initialize(self):
            pass

    import mcp
    import mcp.client.stdio as stdio_mod
    monkeypatch.setattr(stdio_mod, "stdio_client", _FakeStdio)
    monkeypatch.setattr(mcp, "ClientSession", _FakeSession)

    from server.mcp.session import MCPSessionManager
    mgr = MCPSessionManager()
    _client, stack = await mgr._open_session(
        {"id": 1, "transport": "stdio", "command": "mytool", "args": [],
         "env": {"PATH": "/custom/only"}}
    )
    await stack.aclose()
    assert captured["params"].env["PATH"] == "/custom/only"
