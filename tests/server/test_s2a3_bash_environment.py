"""S2a-3 a (the user's decision, 2026-10-22): commands run in /bin/bash, and nothing outside the command's text
changes how it is read.

Two walls, each tested on its own: child_environment is an allowlist, so BASH_ENV, ENV and exported functions
(BASH_FUNC_*) never reach a command; and bash runs in privileged mode (-p), which ignores all three even if one
got through. The direct test runs bash with and without -p, so it can tell the two apart."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from server.mcp.spawn_env import child_environment
from server.services import terminal_exec

BASH = "/bin/bash"
pytestmark = pytest.mark.skipif(not os.path.exists(BASH), reason="no /bin/bash here")


def _hostile_env(tmp_path) -> dict:
    startup = tmp_path / "startup.sh"
    startup.write_text(f"touch {tmp_path / 'sourced'}\n")
    return {"BASH_ENV": str(startup), "ENV": str(startup),
            # the exported-function format bash 3.2.57 (macOS) and current bash both import
            "BASH_FUNC_imported%%": "() { echo imported; }"}


def _run(argv, env, cwd):
    return subprocess.run(argv, env={"PATH": "/usr/bin:/bin", **env}, cwd=cwd, capture_output=True, text=True,
                          timeout=10)


def test_privileged_mode_ignores_startup_files_and_exported_functions(tmp_path):
    env = _hostile_env(tmp_path)
    plain = _run([BASH, "-c", "imported"], env, tmp_path)
    assert (tmp_path / "sourced").exists() and "imported" in plain.stdout     # the attack works without -p …
    (tmp_path / "sourced").unlink()
    guarded = _run([BASH, "-p", "-c", "imported"], env, tmp_path)
    assert not (tmp_path / "sourced").exists()                                # … and -p stops all of it
    assert "imported" not in guarded.stdout and guarded.returncode != 0


def test_the_child_environment_never_carries_them(monkeypatch, tmp_path):
    for key, value in _hostile_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    env = child_environment({}, {"PATH": "/usr/bin:/bin"})
    assert not {"BASH_ENV", "ENV"} & set(env)
    assert not [k for k in env if k.startswith("BASH_FUNC_")]


async def test_a_command_never_sees_them(monkeypatch, tmp_path):
    for key, value in _hostile_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    out = await terminal_exec.run('printf "%s|%s|" "${BASH_ENV-unset}" "${ENV-unset}"; type imported || true',
                                  cwd=tmp_path)
    assert out["stdout"].startswith("unset|unset|")
    assert "imported is a function" not in out["stdout"]
    assert not (tmp_path / "sourced").exists()


@pytest.mark.skipif(shutil.which("zsh") is None, reason="no zsh here")
async def test_the_user_s_zshenv_is_not_read(monkeypatch, tmp_path):
    """zsh -c read ~/.zshenv before every command; bash -p -c reads no startup file."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshenv").write_text(f"touch {tmp_path / 'zshenv-read'}\n")
    (home / ".bashrc").write_text(f"touch {tmp_path / 'bashrc-read'}\n")
    monkeypatch.setenv("HOME", str(home))
    out = await terminal_exec.run("echo ok", cwd=tmp_path)
    assert out["ok"] and out["stdout"].strip() == "ok"
    assert not (tmp_path / "zshenv-read").exists() and not (tmp_path / "bashrc-read").exists()
