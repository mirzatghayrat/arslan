"""HR-1 (v0.1.64) under real seatbelt: the files that make something run later are refused to plain writes.

In the commands preset (the product's `commands_profile`, through SBX's harness, under a scratch HOME): a plain write
to one name of each family in the work folder is refused, and a plain write to an ordinary file beside it succeeds
(the instruction files among them). git still commits, branches, checks out and stashes inside the sandbox when no
held file differs; a `git config` write fails there, the compatibility cost, and so do checkout (at exit 0) and a
fast-forward merge that must change a held file git tracks, where the model reads the note. A work folder inside a
node_modules folder has no exemption. CI files are written like any other (#813 review 3: their guard is HR-2b's push
card), and the everyday git flow is measured step by step (the count of steps refused only on `.git/config` decides
HR-1b). The steps refused only on `.git/config` that exit 0, the held-file checkout under the outside floor that holds
them, and that checkout with git's messages in German and Chinese all carry the git note, with one denial (#813
review 4). In the MCP preset: the same in a granted folder and the server's own folder, and an own folder inside
node_modules keeps every name held.

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


#: #813 review 3 (the user's list decision): CI files are ordinary to the sandbox; their guard is HR-2b's push card.
CI_NAMES = [f".github/workflows/{STAND_IN}.yml", ".gitlab-ci.yml", ".circleci/config.yml", "azure-pipelines.yml",
            "Jenkinsfile", "bitbucket-pipelines.yml"]


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_ci_files_are_written_like_any_other_file(sbx):
    _prepare(sbx.work, CI_NAMES)
    assert _write(sbx, sbx.work, CI_NAMES) == {n: "written" for n in CI_NAMES}


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_a_dependency_folder_may_hold_them_and_the_same_names_elsewhere_stay_refused(sbx):
    """#813 review: a package under node_modules ships its own editor and hook files, which nothing runs from there.
    The same names at the work folder's root and in an ordinary nested folder stay refused."""
    dependency = f"node_modules/{STAND_IN}"
    names = [".vscode/tasks.json", ".vscode/settings.json"]
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


HELD_TRACKED = ".vscode/settings.json"
WHO = ["-c", f"user.name={STAND_IN}", "-c", "user.email=zz@example.invalid", "-c", "commit.gpgsign=false"]


def _held_branch(work) -> str:
    """Outside the sandbox: a repository whose `main` has the held file's old content and whose branch the new, beside
    an ordinary file. Checked out on main; returns its HEAD."""
    def commit(content: str, *args: str) -> None:
        (work / HELD_TRACKED).parent.mkdir(parents=True, exist_ok=True)
        for name in (HELD_TRACKED, f"{STAND_IN}.txt"):
            (work / name).write_text(content)
        for step in (args, ["add", "-A"], ["commit", "-qm", content]):
            assert _git(work, *WHO, *step).returncode == 0
    commit("old\n", "init", "-q", "-b", "main")
    commit("new\n", "checkout", "-qb", STAND_IN)
    assert _git(work, "checkout", "-q", "main").returncode == 0
    return _git(work, "rev-parse", "HEAD").stdout


def _explained(monkeypatch, ran, *, cwd, command: str, mode: str = "workspace", hold: bool = False):
    """git's real output through terminal_exec's own result path: the result, the denial on the run trace, and every
    denial noted (SBX-7: exactly one per run)."""
    from server.orchestrator import run_trace
    from server.services import terminal_exec
    noted: list[str] = []
    real_note = run_trace.note_denial

    def counting(code):
        noted.append(code)
        real_note(code)
    monkeypatch.setattr(run_trace, "note_denial", counting)
    result = {"ok": ran.returncode == 0, "exit_code": ran.returncode, "stdout": ran.stdout, "stderr": ran.stderr,
              "cwd": str(cwd), "sandbox": mode}
    if ran.returncode:
        result["error"] = f"exit code {ran.returncode}"
    with run_trace.collecting() as trace:
        terminal_exec.explain(result, cwd=cwd, closed=[], mode=mode, timed_out=False, command=command, hold=hold)
        run_trace.record(tool="run_command", args={}, result=result, ok=result["ok"], error=None, ms=1)
    return result, trace[0].get("denial"), noted


def _noted_once(explained) -> None:
    result, denial, noted = explained
    assert result.get("note") == command_sandbox.git_note() and denial == "eperm" and noted == ["eperm"]


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("command, exit_code, head_moves", [("checkout -q", 0, True), ("merge -q --ff-only", 1, False)])
def test_git_that_must_change_a_tracked_held_file_leaves_it_and_the_model_reads_the_note(sbx, monkeypatch, command,
                                                                                         exit_code, head_moves):
    """#813 review 1: a branch that changes a tracked held file (editor settings). checkout exits 0 with HEAD moved and
    the held file as it was (a later `commit -a` would undo the branch's change); merge --ff-only exits 1. git's real
    output, through terminal_exec's own result path, carries the note at either exit code, with one EPERM denial."""
    head = _held_branch(sbx.work)
    script = f"git {command} {STAND_IN}"
    ran = sbx.run(["/bin/bash", "-p", "-c", script], probe="hr1-git-held-tracked")
    assert ran.returncode == exit_code
    assert (sbx.work / HELD_TRACKED).read_text() == "old\n"                   # the held file kept its old content
    assert (_git(sbx.work, "rev-parse", "HEAD").stdout != head) is head_moves
    assert (sbx.work / f"{STAND_IN}.txt").read_text() == "new\n"          # the ordinary file was updated
    _noted_once(_explained(monkeypatch, ran, cwd=sbx.work, command=script))


#: #813 review 4: the steps refused only on `.git/config` that still exit 0, from the work folder, on `_seed`'s clone.
CONFIG_ONLY = {
    "checkout -b x origin/x": "cd repo && git checkout -q -b x origin/x",
    "checkout of a remote-only branch": "cd repo && git checkout -q x",
    "push -u": f"cd repo && git push -q -u origin {STAND_IN}",
    "branch --set-upstream-to": "cd repo && git branch -q --set-upstream-to=origin/x",
}


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("step", sorted(CONFIG_ONLY))
def test_a_config_only_refusal_at_exit_0_gets_the_note_and_one_denial(sbx, monkeypatch, step):
    """#813 review 4: git exits 0, prints its config-write line naming `.git/config` and leaves the upstream unset.
    The config is unchanged, and the model reads the git note, with one EPERM denial."""
    _seed(sbx.work)
    repo = sbx.work / "repo"
    assert _git(repo, "branch", STAND_IN).returncode == 0                     # for push -u, made outside
    config = (repo / ".git" / "config").read_bytes()
    ran = sbx.run(["/bin/bash", "-p", "-c", CONFIG_ONLY[step]], probe="hr1-git-config-only")
    assert ran.returncode == 0
    assert (repo / ".git" / "config").read_bytes() == config
    _noted_once(_explained(monkeypatch, ran, cwd=sbx.work, command=CONFIG_ONLY[step]))


def _floor_profile(sbx) -> str:
    """The outside floor that holds them (`run_later_in`: let out under this conversation's grant, no click on its own
    card), built under the harness's scratch HOME and temp, as the harness builds its presets."""
    import tempfile
    with pytest.MonkeyPatch.context() as environment:
        for name in ("HOME", "TMPDIR", "ARSLAN_DATA_DIR"):
            environment.setenv(name, sbx.env[name])
        environment.setattr(tempfile, "tempdir", str(sbx.temp))
        return command_sandbox.minimal_profile(offline=True, run_later_in=sbx.work)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["outside-floor"], indirect=True)
def test_under_the_outside_floor_a_checkout_that_must_change_a_held_file_gets_the_note(sbx, monkeypatch):
    """#813 review 4: under the floor that holds them, checkout to a branch whose tracked held file differs exits 0,
    moves HEAD and keeps the old file. The model reads the same git note, with one EPERM denial."""
    head = _held_branch(sbx.work)
    script = f"git checkout -q {STAND_IN}"
    ran = sbx.run(["/bin/bash", "-p", "-c", script], probe="hr1-floor-git-held-tracked", profile=_floor_profile(sbx))
    assert ran.returncode == 0
    assert (sbx.work / HELD_TRACKED).read_text() == "old\n" and (sbx.work / f"{STAND_IN}.txt").read_text() == "new\n"
    assert _git(sbx.work, "rev-parse", "HEAD").stdout != head
    _noted_once(_explained(monkeypatch, ran, cwd=sbx.work, command=script, mode="outside", hold=True))


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("language", ["de_DE.UTF-8", "zh_CN.UTF-8"])
def test_in_another_language_the_held_file_checkout_still_gets_the_note(sbx, monkeypatch, language):
    """#813 review 4: commands inherit LANG and LC_ALL. git translates its words (here at least the prefix), never
    the path, so the note is keyed on the path. Skipped when this git has no translation for the language."""
    import re
    head = _held_branch(sbx.work)
    sbx.env.update(LANG=language, LC_ALL=language)
    script = f"git checkout -q {STAND_IN}"
    ran = sbx.run(["/bin/bash", "-p", "-c", script], probe="hr1-git-held-tracked-language")
    assert ran.returncode == 0 and _git(sbx.work, "rev-parse", "HEAD").stdout != head
    assert (sbx.work / HELD_TRACKED).read_text() == "old\n"
    if not ran.stderr.strip() or re.search(r"^(?:error|warning|fatal): ", ran.stderr, re.M):
        pytest.skip(f"this git printed no translated line for {language}")
    _noted_once(_explained(monkeypatch, ran, cwd=sbx.work, command=script))


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands", "mcp"], indirect=True)
def test_a_work_folder_inside_a_dependency_folder_keeps_every_name_held(sbx):
    """#813 review 2: the exemption is for node_modules below the work folder only. A work folder whose real path
    already passes through one holds every name, a nested node_modules below it included. In the MCP preset the work
    folder is the server's own folder, with no grant: only its `roots=` decides it (#813 review 4)."""
    sbx.work = sbx.root / "node_modules" / STAND_IN / "work"
    sbx.work.mkdir(parents=True)
    names = [".vscode/tasks.json", ".vscode/settings.json", f"node_modules/{STAND_IN}/.npmrc"]
    _prepare(sbx.work, (*names, f"{STAND_IN}.txt"))
    assert _write(sbx, sbx.work, (*names, f"{STAND_IN}.txt")) == {**{n: "refused" for n in names},
                                                                   f"{STAND_IN}.txt": "written"}


# ── the everyday git flow, measured (#813 review 3: decides HR-1b) ──────────

def _refused(stderr: str) -> tuple[str, ...]:
    """The held names git's EPERM lines name: `.git/config` (config.worktree included), `.git/hooks`, `.husky`."""
    found = set()
    for line in stderr.splitlines():
        if "Operation not permitted" not in line:
            continue
        found.add(".git/config" if "/config" in line or "config file" in line else
                  ".git/hooks" if ".git/hooks" in line else ".husky" if ".husky" in line else "other")
    return tuple(sorted(found))


def _out(folder, *args) -> str | None:
    if not folder.is_dir():
        return None
    ran = _git(folder, *args)
    return ran.stdout.strip() if ran.returncode == 0 else None


def _upstream(repo, branch: str) -> str | None:
    return _out(repo, "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")


#: Each step, run in the sandbox from the work folder, in this order on one clone (`repo`) of a bare origin kept in
#: the work folder (so a push lands inside it), and how to read its effect afterwards, outside the sandbox.
FLOW = [
    ("clone", "git clone -q origin.git cloned"),
    ("init", "git init -q fresh"),
    # The same two without git's hook templates (sample hooks, which never run): what is refused beneath them.
    ("clone --template=", "git clone -q --template= origin.git cloned-bare-template"),
    ("init --template=", "git init -q --template= fresh-bare-template"),
    ("checkout -b x origin/x", "cd repo && git checkout -q -b x origin/x"),
    ("switch -c y", "cd repo && git switch -q -c y"),
    ("push -u origin y", "cd repo && git push -q -u origin y"),
    ("branch --set-upstream-to", "cd repo && git branch -q --set-upstream-to=origin/x"),
    ("fetch", "cd repo && git fetch -q"),
    ("pull --ff-only", "cd repo && git switch -q main && git pull -q --ff-only"),
    ("commit, switch", f"cd repo && echo z >> {STAND_IN}.txt && git {' '.join(WHO)} commit -qam z "
                       "&& git switch -q y && git switch -q main"),
    ("remote add", "cd repo && git remote add other ../origin.git"),
    ("config core.hooksPath (husky)", "cd repo && git config core.hooksPath .husky/_"),
    ("write .husky/_ (husky)", f"cd repo && mkdir -p .husky/_ && echo zz > .husky/_/{STAND_IN}"),
    ("config user.name", f"cd repo && git config user.name {STAND_IN}"),
]


def _effect(work, step: str, before: dict) -> str:
    repo, origin = work / "repo", work / "origin.git"
    if step.startswith("clone"):
        folder = work / ("cloned" if step == "clone" else "cloned-bare-template")
        return "yes" if _out(folder, "rev-parse", "--verify", "-q", "origin/x") else "no"
    if step.startswith("init"):
        folder = work / ("fresh" if step == "init" else "fresh-bare-template")
        return "yes" if _out(folder, "rev-parse", "--git-dir") else "no"
    if step == "checkout -b x origin/x":
        if _out(repo, "branch", "--show-current") != "x":
            return "no"
        return "yes" if _upstream(repo, "x") == "origin/x" else "branch made, no upstream"
    if step == "switch -c y":
        return "yes" if _out(repo, "branch", "--show-current") == "y" else "no"
    if step == "push -u origin y":
        if not _out(origin, "rev-parse", "--verify", "-q", "refs/heads/y"):
            return "no"
        return "yes" if _upstream(repo, "y") == "origin/y" else "pushed, no upstream"
    if step == "branch --set-upstream-to":
        return "yes" if _upstream(repo, "y") == "origin/x" else "no"
    if step == "fetch":
        return "yes" if _out(repo, "rev-parse", "origin/main") == _out(origin, "rev-parse", "main") else "no"
    if step == "pull --ff-only":
        return "yes" if _out(repo, "rev-parse", "HEAD") == _out(origin, "rev-parse", "main") else "no"
    if step == "commit, switch":
        moved = _out(repo, "rev-parse", "HEAD~1") == before["head"]
        return "yes" if moved and _out(repo, "branch", "--show-current") == "main" else "no"
    if step == "remote add":
        return "yes" if "other" in (_out(repo, "remote") or "").split() else "no"
    if step == "config core.hooksPath (husky)":
        return "yes" if _out(repo, "config", "core.hooksPath") == ".husky/_" else "no"
    if step == "write .husky/_ (husky)":
        return "yes" if (repo / ".husky" / "_" / STAND_IN).exists() else "no"
    assert step == "config user.name"
    return "yes" if _out(repo, "config", "user.name") == STAND_IN else "no"


CONFIG, HOOKS, HUSKY = (".git/config",), (".git/hooks",), (".husky",)
#: What was measured on macOS 26.6 (Apple git, 2026-11-10): step -> (exit code, held writes refused, effect). Three
#: config refusals exit 0: a tracking checkout and `push -u` do the rest and leave no upstream, `--set-upstream-to`
#: does nothing. clone and init are refused copying git's sample hooks first, and the config beneath them.
FLOW_MEASURED = {
    "clone": (1, HOOKS, "no"),
    "init": (1, HOOKS, "no"),
    "clone --template=": (128, CONFIG, "no"),
    "init --template=": (128, CONFIG, "no"),
    "checkout -b x origin/x": (0, CONFIG, "branch made, no upstream"),
    "switch -c y": (0, (), "yes"),
    "push -u origin y": (0, CONFIG, "pushed, no upstream"),
    "branch --set-upstream-to": (0, CONFIG, "no"),
    "fetch": (0, (), "yes"),
    "pull --ff-only": (0, (), "yes"),
    "commit, switch": (0, (), "yes"),
    "remote add": (128, CONFIG, "no"),
    "config core.hooksPath (husky)": (4, CONFIG, "no"),
    "write .husky/_ (husky)": (1, HUSKY, "no"),
    "config user.name": (4, CONFIG, "no"),
}
#: Of the everyday steps (the two template-free rows are diagnostics, not steps), the ones that fail only because of
#: `.git/config`: the tracking checkout, push -u, set-upstream-to, remote add, the husky config line, user.name.
FLOW_CONFIG_ONLY = 6


def _seed(work) -> None:
    """Outside the sandbox: a bare origin with `main` and `x`, and a clone of it (`repo`)."""
    assert _git(work, "init", "-q", "--bare", "-b", "main", "origin.git").returncode == 0
    assert _git(work, "init", "-q", "-b", "main", "seed").returncode == 0
    seed = work / "seed"
    for step in (["remote", "add", "origin", "../origin.git"], ["commit", "-q", "--allow-empty", "-m", "one"]):
        assert _git(seed, *WHO, *step).returncode == 0
    (seed / f"{STAND_IN}.txt").write_text("one\n")
    for step in (["add", "-A"], ["commit", "-qm", "two"], ["push", "-q", "origin", "main"],
                 ["checkout", "-qb", "x"], ["commit", "-q", "--allow-empty", "-m", "x"], ["push", "-q", "origin", "x"],
                 ["checkout", "-q", "main"]):
        assert _git(seed, *WHO, *step).returncode == 0, step
    assert _git(work, "clone", "-q", "origin.git", "repo").returncode == 0


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_the_everyday_git_flow_in_the_sandbox(sbx):
    """#813 review 3: each everyday git step in the commands preset, its exit code, the held write it was refused
    (git's own EPERM line), and whether its effect happened. The steps that fail only on `.git/config` decide HR-1b
    (a one-click grant for git to update this repository's config); the count is asserted below."""
    _seed(sbx.work)
    measured = {}
    for step, script in FLOW:
        if step == "fetch":                                            # origin moves on, outside the sandbox
            seed = sbx.work / "seed"
            for args in (["commit", "-q", "--allow-empty", "-m", "three"], ["push", "-q", "origin", "main"]):
                assert _git(seed, *WHO, *args).returncode == 0
        before = {"head": _out(sbx.work / "repo", "rev-parse", "HEAD")}
        ran = sbx.run(["/bin/bash", "-p", "-c", script], probe="hr1-git-flow")
        measured[step] = (ran.returncode, _refused(ran.stderr), _effect(sbx.work, step, before))
    assert measured == FLOW_MEASURED, json.dumps(measured)
    config_only = [s for s, (_, refused, effect) in measured.items()
                   if effect != "yes" and refused == CONFIG and "--template=" not in s]
    assert len(config_only) == FLOW_CONFIG_ONLY
