"""HR-1 (v0.1.64) under real seatbelt: the files that make something run later are refused to plain writes.

In the commands preset (the product's `commands_profile`, through SBX's harness, under a scratch HOME): a plain write
to one name of each family in the work folder is refused, and a plain write to an ordinary file beside it succeeds
(the instruction files among them). git still commits, branches, checks out and stashes inside the sandbox; a
`git config` write fails there, the compatibility cost. In the MCP preset: the same in a granted folder and the
server's own folder.

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
