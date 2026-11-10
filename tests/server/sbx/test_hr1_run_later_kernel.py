"""HR-1 (v0.1.64) under real seatbelt: the files that make something run later are refused to plain writes.

In the commands preset (the product's `commands_profile`, through SBX's harness, under a scratch HOME): a plain write
to one name of each family in the work folder is refused, and a plain write to an ordinary file beside it succeeds
(the instruction files among them). git still commits, branches, checks out and stashes inside the sandbox when no
held file differs; a `git config` write fails there, the compatibility cost, and so do checkout (at exit 0) and a
fast-forward merge that must change a held file git tracks, where the model reads the note. A work folder inside a
node_modules folder has no exemption. In the MCP preset: the same in a granted folder and the server's own folder.

Plain writes with stand-in names only. The bypass corpus (letter case, Unicode forms, renames into place, hard links,
a `.git` that is a link or a file, submodules, bare repositories, a hooksPath pointing outside) is Codex's.
"""
import json
import os
import subprocess
import sys

import pytest

from server.services import command_sandbox

STAND_IN = "zz-stand-in-word"
macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

# family: (a held name, an ordinary file beside it). Folders are made before the run: making them is held too.
FAMILIES = {
    "git": (f".git/hooks/{STAND_IN}", f".git/{STAND_IN}"),
    "envrc": (".envrc", f"{STAND_IN}.txt"),
    "ci": (f".github/workflows/{STAND_IN}.yml", f".github/{STAND_IN}.md"),
    "editor": (".vscode/tasks.json", f".vscode/{STAND_IN}.json"),
    "agent": (".claude/settings.json", "CLAUDE.md"),
    "package": (".npmrc", "AGENTS.md"),
    "hooks": (".pre-commit-config.yaml", f"{STAND_IN}.yaml"),
}

_WRITE = """
import json, pathlib, sys
out = {}
for name in sys.argv[1:]:
    try:
        pathlib.Path(name).write_text('zz')
    except PermissionError:
        out[name] = 'refused'
    else:
        out[name] = 'written'
print(json.dumps(out))
"""


def _prepare(folder, names) -> None:
    for name in names:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)


def _write(sbx, folder, names) -> dict:
    result = sbx.python(_WRITE, *(folder / name for name in names), probe="hr1-plain-write")
    assert result.returncode == 0, result.stderr
    return {os.path.relpath(k, folder): v for k, v in json.loads(result.stdout).items()}


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_a_plain_write_to_each_family_is_refused_and_one_beside_it_is_not(sbx, family):
    held, beside = FAMILIES[family]
    _prepare(sbx.work, (held, beside))
    assert _write(sbx, sbx.work, (held, beside)) == {held: "refused", beside: "written"}
    assert not (sbx.work / held).exists() and (sbx.work / beside).read_text() == "zz"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_a_dependency_folder_may_hold_them_and_the_same_names_elsewhere_stay_refused(sbx):
    """#813 review: a package under node_modules ships its own CI and editor files, which nothing runs from there.
    The same names at the work folder's root and in an ordinary nested folder stay refused."""
    dependency = f"node_modules/{STAND_IN}"
    names = [".github/workflows/ci.yml", ".vscode/settings.json"]
    inside = [f"{dependency}/{n}" for n in names]
    outside = [*names, *(f"{STAND_IN}-lib/{n}" for n in names), *(f"not-node_modules/{n}" for n in names)]
    _prepare(sbx.work, (*inside, *outside))
    assert _write(sbx, sbx.work, (*inside, *outside)) == {**{n: "written" for n in inside},
                                                          **{n: "refused" for n in outside}}


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["mcp"], indirect=True)
def test_an_mcp_server_cannot_write_them_in_a_granted_folder(sbx):
    granted = sbx.root / "granted"
    granted.mkdir()
    sbx.granted_folders = [granted]
    names = [n for pair in FAMILIES.values() for n in pair]
    _prepare(granted, names)
    _prepare(sbx.work, names)
    expected = {n: "refused" if n == held else "written" for held, beside in FAMILIES.values() for n in (held, beside)}
    assert _write(sbx, granted, names) == expected
    assert _write(sbx, sbx.work, names) == expected                       # its own folder too


def _git(folder, *args) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(folder.parent), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(["git", *args], cwd=folder, env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_git_still_commits_branches_checks_out_and_stashes_in_the_sandbox(sbx):
    # The repository is made outside the sandbox: `git init` writes .git/config and .git/hooks, which it refuses.
    assert _git(sbx.work, "init", "-q").returncode == 0
    (sbx.work / f"{STAND_IN}.txt").write_text("one\n")
    config = (sbx.work / ".git" / "config").read_bytes()
    who = f"-c user.name={STAND_IN} -c user.email=zz@example.invalid -c commit.gpgsign=false"
    script = (f"set -eu\ngit add {STAND_IN}.txt\ngit {who} commit -qm one\ngit branch {STAND_IN}\n"
              f"git checkout -q {STAND_IN}\necho two >> {STAND_IN}.txt\ngit {who} stash -q\ngit stash pop -q\n"
              f"git {who} commit -qam two\ngit log --oneline | wc -l\n")
    result = sbx.run(["/bin/bash", "-p", "-c", script], probe="hr1-git-everyday")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["2"]
    # The compatibility cost: a config write (as remote add, set-upstream and init make) is refused.
    refused = sbx.run(["/bin/bash", "-p", "-c", f"git config {STAND_IN}.key value"], probe="hr1-git-config")
    assert refused.returncode != 0 and (sbx.work / ".git" / "config").read_bytes() == config


HELD_CI = f".github/workflows/{STAND_IN}.yml"
WHO = ["-c", f"user.name={STAND_IN}", "-c", "user.email=zz@example.invalid", "-c", "commit.gpgsign=false"]


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("command, exit_code, head_moves", [("checkout -q", 0, True), ("merge -q --ff-only", 1, False)])
def test_git_that_must_change_a_tracked_held_file_leaves_it_and_the_model_reads_the_note(sbx, command, exit_code,
                                                                                         head_moves):
    """#813 review 1: a branch that changes a tracked CI file. checkout exits 0 with HEAD moved and the CI file as it
    was (a later `commit -a` would undo the branch's change); merge --ff-only exits 1. git's real output, through
    terminal_exec's own result path, carries the note at either exit code, with one EPERM denial."""
    from server.orchestrator import run_trace
    from server.services import terminal_exec
    # The repository is made outside the sandbox, as above: main has the old content, the branch the new.
    def commit(content: str, *args: str) -> None:
        (sbx.work / HELD_CI).parent.mkdir(parents=True, exist_ok=True)
        for name in (HELD_CI, f"{STAND_IN}.txt"):
            (sbx.work / name).write_text(content)
        for step in (args, ["add", "-A"], ["commit", "-qm", content]):
            assert _git(sbx.work, *WHO, *step).returncode == 0
    commit("old\n", "init", "-q", "-b", "main")
    commit("new\n", "checkout", "-qb", STAND_IN)
    assert _git(sbx.work, "checkout", "-q", "main").returncode == 0
    head = _git(sbx.work, "rev-parse", "HEAD").stdout
    ran = sbx.run(["/bin/bash", "-p", "-c", f"git {command} {STAND_IN}"], probe="hr1-git-held-tracked")
    assert ran.returncode == exit_code
    assert (sbx.work / HELD_CI).read_text() == "old\n"                     # the held file kept its old content
    assert (_git(sbx.work, "rev-parse", "HEAD").stdout != head) is head_moves
    assert (sbx.work / f"{STAND_IN}.txt").read_text() == "new\n"          # the ordinary file was updated
    result = {"ok": ran.returncode == 0, "exit_code": ran.returncode, "stdout": ran.stdout, "stderr": ran.stderr,
              "cwd": str(sbx.work), "sandbox": "workspace"}
    if ran.returncode:
        result["error"] = f"exit code {ran.returncode}"
    with run_trace.collecting() as trace:
        terminal_exec.explain(result, cwd=sbx.work, closed=[], mode="workspace", timed_out=False)
        run_trace.record(tool="run_command", args={}, result=result, ok=result["ok"], error=None, ms=1)
    assert "partly updated" in result["note"] and "git status" in result["note"]
    assert trace[0].get("denial") == "eperm"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_a_work_folder_inside_a_dependency_folder_keeps_every_name_held(sbx):
    """#813 review 2: the exemption is for node_modules below the work folder only. A work folder whose real path
    already passes through one holds every name, a nested node_modules below it included."""
    sbx.work = sbx.root / "node_modules" / STAND_IN / "work"
    sbx.work.mkdir(parents=True)
    names = [".github/workflows/ci.yml", ".vscode/settings.json", f"node_modules/{STAND_IN}/.npmrc"]
    _prepare(sbx.work, (*names, f"{STAND_IN}.txt"))
    assert _write(sbx, sbx.work, (*names, f"{STAND_IN}.txt")) == {**{n: "refused" for n in names},
                                                                   f"{STAND_IN}.txt": "written"}
