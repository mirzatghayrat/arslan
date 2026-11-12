"""HR-1c, D (v0.1.64): git's own view of each repository, compared around one command.

Each case runs `git_config_guard.snapshot(view=True)`, changes the tree as the command would (the command's effect,
simulated here; the real-seatbelt cases are in tests/server/sbx/test_hr1c_git_view_kernel.py), then `restore`:

- the hard requirement: a repository whose config names a stand-in program for fsmonitor, an include and a textconv
  runs none of them while D asks git (a `git status` beside it does run the first: the config is live);
- git is asked under the pinned environment, in sandbox-exec's read-only profile; a failure or a timeout is named;
- the plain cases: a hook that appeared during the command is quarantined, one placed before it isn't; samples stay;
  a `.git` replaced by a `gitdir:` file, `commondir`, a new repository, an ordinary commit, no repository;
- Codex's round-3 classes, one plain stand-in each: a link, a git file, shared metadata, a nested and a slash
  submodule, a bare repository, an included hooksPath;
- HR-1b's walk finds each kind of repository; the allowlist without the grant, through terminal_exec.

Stand-in names only; the adversarial shapes are Codex's corpus.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from server.services import command_sandbox, git_config_guard, terminal_exec

STAND_IN = "zz-stand-in-word"
seatbelt = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                              reason="git is asked in seatbelt, which is macOS-only")


def _git(folder: Path, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(folder), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_TEMPLATE_DIR": "", "GIT_AUTHOR_NAME": "zz", "GIT_AUTHOR_EMAIL": "zz@example.invalid",
           "GIT_COMMITTER_NAME": "zz", "GIT_COMMITTER_EMAIL": "zz@example.invalid"}
    ran = subprocess.run(["git", *args], cwd=folder, env=env, capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    return ran


def _init(path: Path, *flags: str) -> Path:
    """A repository with no template (no sample hooks); its git folder."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", *flags)
    return path if "--bare" in flags else path / ".git"


def _hook(folder: Path, name: str = "pre-commit") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(f"#!/bin/sh\n# {STAND_IN}\n")
    (folder / name).chmod(0o755)
    return folder / name


def _snap(ws: Path) -> git_config_guard.Snapshot:
    """D's snapshot as terminal_exec takes it without the grant."""
    return git_config_guard.snapshot(ws, grant=False, view=True)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(git_config_guard, "QUARANTINE", tmp_path / "quarantine")
    folder = tmp_path / "ws"
    folder.mkdir()
    return Path(os.path.realpath(folder))


def _quarantined(tmp_path: Path) -> list[str]:
    base = tmp_path / "quarantine"
    return sorted(name.split("-", 1)[1] for box in base.iterdir() for name in os.listdir(box)) if base.exists() else []


# ── the hard requirement ─────────────────────────────────────────────────────

@pytest.mark.macos
@seatbelt
def test_d_runs_nothing_a_repository_names(ws, tmp_path):
    marker = tmp_path / "marker"
    program = tmp_path / f"{STAND_IN}.sh"
    program.write_text(f"#!/bin/sh\necho ran >> {marker}\n")
    program.chmod(0o755)
    included = tmp_path / f"{STAND_IN}.cfg"
    included.write_text(f"[core]\n\tpager = {program}\n\teditor = {program}\n")
    git = _init(ws / "r")
    with (git / "config").open("a") as config:
        config.write(f"[core]\n\tfsmonitor = {program}\n[include]\n\tpath = {included}\n"
                     f"[diff \"{STAND_IN}\"]\n\ttextconv = {program}\n")
    (ws / "r" / ".gitattributes").write_text(f"* diff={STAND_IN}\n")
    (ws / "r" / "a.txt").write_text("one\n")
    saved = _snap(ws)
    (ws / "r" / "a.txt").write_text("two\n")
    git_config_guard.restore(saved)
    assert not marker.exists()
    assert saved.repos[git] is not None and saved.included[git] is not None
    # The control: git itself, asked for a status, runs the fsmonitor program this config names.
    subprocess.run(["git", "status"], cwd=ws / "r", capture_output=True, timeout=60,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"})
    assert marker.exists()


@pytest.mark.macos
@seatbelt
def test_git_is_asked_with_the_pinned_environment_in_a_read_only_profile(ws, tmp_path, monkeypatch):
    git = _init(ws / "r")
    for name, value in {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
                        "GIT_CONFIG_VALUE_0": str(tmp_path / STAND_IN), "GIT_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(name, value)
    started = []
    real = subprocess.Popen

    def popen(argv, **kw):
        started.append((argv, kw["env"]))
        return real(argv, **kw)
    monkeypatch.setattr(git_config_guard.subprocess, "Popen", popen)
    answer = git_config_guard.view([git])[git]
    assert answer == (git, git, git / "hooks")                  # the caller's GIT_CONFIG_* never reached git
    (argv, env), = started
    assert argv[:2] == ["/usr/bin/sandbox-exec", "-p"] and "(deny default)" in argv[2]
    assert "(deny network*)" in argv[2] and "(allow network" not in argv[2]
    assert not any(name.startswith("GIT_") for name in env if name not in
                   ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_TERMINAL_PROMPT", "GIT_CEILING_DIRECTORIES"))
    assert env["XDG_CONFIG_HOME"] == "" and env["GIT_CONFIG_GLOBAL"] == os.devnull and env["HOME"] != os.environ["HOME"]
    assert "rev-parse" in argv and "core.fsmonitor=false" in argv and not {"status", "diff", "log"} & set(argv)


@pytest.mark.parametrize("how", ["timeout", "failure"])
def test_git_failing_or_timing_out_fails_closed_with_a_note(ws, monkeypatch, how):
    git = _init(ws / "r")
    if how == "timeout":
        monkeypatch.setattr(git_config_guard, "VIEW_TIMEOUT_S", 0)
    else:
        monkeypatch.setattr(git_config_guard, "_SANDBOX_EXEC", str(ws / f"{STAND_IN}-missing"))
    saved = _snap(ws)
    assert saved.repos == {git: None}
    _hook(git / "hooks")                                          # still compared, by the folder itself
    outcome = git_config_guard.restore(saved)
    assert outcome.unanswered == [os.path.join("r", ".git")] and outcome.quarantined == ["pre-commit"]
    assert "couldn't ask git" in outcome.message() and "Tell the user" in outcome.message()


# ── the plain cases ──────────────────────────────────────────────────────────

@pytest.mark.macos
@seatbelt
def test_a_hook_that_appeared_during_the_command_is_quarantined_and_one_from_before_is_not(ws, tmp_path):
    git = _init(ws / "r")
    _hook(git / "hooks", "post-checkout")                         # placed before the command: not D's business
    saved = _snap(ws)
    _hook(git / "hooks")
    _hook(git / "hooks", f"{STAND_IN}.sample")                    # git never runs a sample
    outcome = git_config_guard.restore(saved)
    assert outcome.quarantined == ["pre-commit"] and _quarantined(tmp_path) == ["pre-commit"]
    assert sorted(os.listdir(git / "hooks")) == ["post-checkout", f"{STAND_IN}.sample"]
    kept = next((tmp_path / "quarantine").iterdir()) / "0-pre-commit"
    assert not stat.S_IMODE(kept.stat().st_mode) & 0o111
    assert "pre-commit" in outcome.message() and STAND_IN not in outcome.message()


@pytest.mark.macos
@seatbelt
def test_a_changed_hook_is_quarantined_too(ws, tmp_path):
    git = _init(ws / "r")
    hook = _hook(git / "hooks")
    saved = _snap(ws)
    hook.write_text("#!/bin/sh\n# changed\n")
    assert git_config_guard.restore(saved).quarantined == ["pre-commit"] and not hook.exists()


@pytest.mark.macos
@seatbelt
@pytest.mark.parametrize("inside", [True, False])
def test_a_git_folder_replaced_by_a_gitdir_file(ws, tmp_path, inside):
    """Inside the work folder the stand-in's hook is quarantined; outside it, the new `.git` file is renamed aside."""
    _init(ws / "r")
    saved = _snap(ws)
    stand_in = _init((ws if inside else tmp_path) / f"{STAND_IN}.git", "--bare")
    _hook(stand_in / "hooks")
    os.rename(ws / "r" / ".git", ws / f"{STAND_IN}-old")
    (ws / "r" / ".git").write_text(f"gitdir: {stand_in}\n")
    outcome = git_config_guard.restore(saved)
    assert outcome.moved == [os.path.join("r", ".git")]
    if inside:
        assert outcome.quarantined == ["pre-commit"] and outcome.aside == []
    else:
        assert outcome.quarantined == [] and outcome.aside == [os.path.join("r", ".git")]
        assert not (ws / "r" / ".git").exists() and (stand_in / "hooks" / "pre-commit").exists()


@pytest.mark.macos
@seatbelt
def test_a_changed_commondir_is_named(ws, tmp_path):
    git = _init(ws / "r")
    elsewhere = _init(tmp_path / f"{STAND_IN}.git", "--bare")
    saved = _snap(ws)
    (git / "commondir").write_text(f"{elsewhere}\n")
    outcome = git_config_guard.restore(saved)
    assert outcome.moved == [os.path.join("r", ".git")] and "r/.git" in outcome.message()


@pytest.mark.macos
@seatbelt
def test_a_new_repository_with_a_hook_is_quarantined(ws, tmp_path):
    _init(ws / "r")
    saved = _snap(ws)
    _hook(_init(ws / "fresh") / "hooks", "post-checkout")
    outcome = git_config_guard.restore(saved)
    assert outcome.quarantined == ["post-checkout"] and outcome.moved == []


@pytest.mark.macos
@seatbelt
def test_an_ordinary_commit_gets_no_note_and_no_quarantine(ws, tmp_path):
    _init(ws / "r")
    saved = _snap(ws)
    (ws / "r" / "a.txt").write_text("one\n")
    _git(ws / "r", "add", "a.txt")
    _git(ws / "r", "commit", "-qm", "one")
    outcome = git_config_guard.restore(saved)
    assert outcome.message() == "" and _quarantined(tmp_path) == []


def test_with_no_repository_git_is_never_asked(ws, monkeypatch):
    (ws / "a" / "b").mkdir(parents=True)

    def never(*a, **k):
        raise AssertionError("git was asked")
    monkeypatch.setattr(git_config_guard.subprocess, "Popen", never)
    saved = _snap(ws)
    assert saved.repos == {} and git_config_guard.restore(saved).message() == ""


def test_past_the_walks_cap_the_snapshot_fails_closed(ws, monkeypatch):
    for name in ("a", "b", "c"):
        (ws / name).mkdir()
    monkeypatch.setattr(git_config_guard, "MAX_FOLDERS", 3)
    with pytest.raises(git_config_guard.GuardError):
        _snap(ws)


def _git_folder(path: Path) -> Path:
    """What git takes for a git folder: HEAD, objects and refs."""
    for name in ("objects", "refs"):
        (path / name).mkdir(parents=True)
    (path / "HEAD").write_text("ref: refs/heads/main\n")
    return path


def test_hr1bs_walk_finds_each_kind_of_repository_skips_node_modules_and_never_follows_a_link(tmp_path):
    """A `.git` folder or file, a submodule's git folder at any depth or with `/` in its name, a bare repository; not
    inside node_modules, not through a link, and never inside a git folder but its modules. The configs the grant
    lifts are unchanged."""
    ws = tmp_path / "ws"
    git = _git_folder(ws / "r" / ".git")
    (git / "config").write_text("")
    nested = _git_folder(git / "modules" / "a")
    deeper = _git_folder(nested / "modules" / "b")
    slashed = _git_folder(git / "modules" / "x" / "y")
    _git_folder(git / "worktrees" / STAND_IN)                               # git's own, not walked into
    inner = _git_folder(ws / "r" / f"{STAND_IN}-nested" / ".git")
    (ws / "wt").mkdir()
    (ws / "wt" / ".git").write_text(f"gitdir: {git}\n")
    bare = _git_folder(ws / f"{STAND_IN}.git")
    _git_folder(ws / "node_modules" / STAND_IN / ".git")
    (ws / f"{STAND_IN}-link").symlink_to(ws / "node_modules")
    configs, repos = git_config_guard._walk(ws)
    assert sorted(repos) == sorted([git, nested, deeper, slashed, inner, ws / "wt" / ".git", bare])
    assert configs == git_config_guard.config_files(ws) == [git / "config"]


def test_the_configs_are_the_ones_git_reads_that_exist(tmp_path):
    common = tmp_path / "common"
    git = common / "worktrees" / "w"
    other = common / "worktrees" / STAND_IN
    for path in (common / "config", common / "config.worktree", git / "config.worktree", other / "config.worktree",
                 common / "hooks" / "config"):                               # the last is not a config git reads
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    assert sorted(git_config_guard._configs((git, common, common / "hooks"))) == sorted(
        [common / "config", common / "config.worktree", git / "config.worktree", other / "config.worktree"])
    assert git_config_guard._configs((tmp_path / "none", tmp_path / "none", tmp_path)) == []


# ── Codex's round-3 classes, one plain stand-in each ─────────────────────────

def _linked_git(ws: Path) -> Path:
    real = _init(ws / f"{STAND_IN}-gitdir", "--bare")            # a folder named otherwise, `.git` a link to it
    (ws / "r").mkdir()
    (ws / "r" / ".git").symlink_to(real)
    return real / "hooks"


def _linked_hooks(ws: Path) -> Path:
    git = _init(ws / "r")
    (git / "hooks").mkdir()
    return git / "hooks"                                          # replaced by a link during the command (below)


def _git_file(ws: Path) -> Path:
    real = _init(ws / f"{STAND_IN}-gitdir", "--bare")
    (ws / "r").mkdir()
    (ws / "r" / ".git").write_text(f"gitdir: ../{STAND_IN}-gitdir\n")
    return real / "hooks"


def _worktree(ws: Path) -> Path:
    git = _init(ws / "main")
    (ws / "main" / "a.txt").write_text("one\n")
    _git(ws / "main", "add", "a.txt")
    _git(ws / "main", "commit", "-qm", "one")
    _git(ws / "main", "worktree", "add", "-q", str(ws / "wt"))
    return git / "hooks"                                          # shared through commondir


def _nested_submodule(ws: Path) -> Path:
    return _init(_init(ws / "r") / "modules" / "a" / "modules" / "b", "--bare") / "hooks"


def _slash_submodule(ws: Path) -> Path:
    return _init(_init(ws / "r") / "modules" / "x" / "y", "--bare") / "hooks"


def _bare(ws: Path) -> Path:
    return _init(ws / f"{STAND_IN}.git", "--bare") / "hooks"


def _included_hooks_path(ws: Path) -> Path:
    git = _init(ws / "r")
    (ws / f"{STAND_IN}.cfg").write_text("")
    with (git / "config").open("a") as config:
        config.write(f"[include]\n\tpath = ../../{STAND_IN}.cfg\n")
    return ws / "r" / f"{STAND_IN}-hooks"                         # named by the include during the command (below)


CLASSES = {"symlink .git": _linked_git, "symlink hooks": _linked_hooks, "git-file": _git_file,
           "shared metadata": _worktree, "nested submodule": _nested_submodule, "slash submodule": _slash_submodule,
           "bare repository": _bare, "included hooksPath": _included_hooks_path}


@pytest.mark.macos
@seatbelt
@pytest.mark.parametrize("name", list(CLASSES))
def test_each_round_3_class_has_its_hook_quarantined(ws, tmp_path, name):
    hooks = CLASSES[name](ws)
    saved = _snap(ws)
    if name == "symlink hooks":
        target = ws / f"{STAND_IN}-hooks"
        _hook(target)
        os.rename(hooks, ws / f"{STAND_IN}-old")
        hooks.symlink_to(target)
    elif name == "included hooksPath":
        (ws / f"{STAND_IN}.cfg").write_text(f"[core]\n\thooksPath = {STAND_IN}-hooks\n")
        _hook(hooks)
    else:
        _hook(hooks)
    outcome = git_config_guard.restore(saved)
    assert outcome.quarantined == ["pre-commit"] and outcome.unanswered == [], outcome.message()
    assert outcome.moved == ([os.path.join("r", ".git")] if name in ("symlink hooks", "included hooksPath") else [])
    # HR-1c: the included file that set the hooks path is quarantined too.
    assert outcome.includes_moved == (["core.hookspath in " + f"{STAND_IN}.cfg"] if name == "included hooksPath"
                                      else [])


# ── the allowlist without the grant ──────────────────────────────────────────

@pytest.mark.macos
@seatbelt
async def test_without_the_grant_a_config_changed_through_another_name_is_put_back(ws, monkeypatch):
    real = _init(ws / f"{STAND_IN}-gitdir", "--bare")
    (ws / "r").mkdir()
    (ws / "r" / ".git").symlink_to(real)
    before = (real / "config").read_bytes()
    lifted = []

    async def run(**kw):
        lifted.append(kw.get("git_config_ok", False))
        with (real / "config").open("a") as config:
            config.write(f"[core]\n\thooksPath = {STAND_IN}\n")
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "_run", run)
    result = await terminal_exec.run("true", cwd=ws, sandbox=True, git_config=False)
    assert lifted == [False] and (real / "config").read_bytes() == before
    assert "core.hookspath" in result["git_config_note"] and STAND_IN not in result["git_config_note"]
    # No grant: no baseline kept, and the folder isn't checked before later commands.
    assert not any(ws in Path(os.path.realpath(p)).parents for p in git_config_guard._BASELINES)
    assert ws not in git_config_guard.WATCHED


@pytest.mark.macos
@seatbelt
async def test_terminal_exec_checks_the_outside_floor_too_and_nothing_where_seatbelt_cant_start(ws, monkeypatch):
    """D under the outside floor that holds run-later files, never lifted; not outside without it; not where seatbelt
    can't start."""
    git = _init(ws / "r")
    seen = []

    async def run(**kw):
        seen.append(kw.get("git_config_ok", False))
        _hook(git / "hooks")
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "outside"}
    monkeypatch.setattr(terminal_exec, "_run", run)
    result = await terminal_exec.run("true", cwd=ws, sandbox=False, hold_run_later=True)
    assert seen == [False] and "pre-commit" in result["git_config_note"] and not (git / "hooks" / "pre-commit").exists()
    result = await terminal_exec.run("true", cwd=ws, sandbox=False)
    assert "git_config_note" not in result and (git / "hooks" / "pre-commit").exists()
    (git / "hooks" / "pre-commit").unlink()
    monkeypatch.setattr(command_sandbox, "available", lambda: False)
    result = await terminal_exec.run("true", cwd=ws, sandbox=True)
    assert "git_config_note" not in result and (git / "hooks" / "pre-commit").exists()


async def test_a_folder_that_cant_be_walked_runs_unchecked_and_says_so(ws, monkeypatch):
    monkeypatch.setattr(command_sandbox, "available", lambda: True)

    def failing(folder, closed=(), **kw):
        raise git_config_guard.GuardError("stand-in")
    monkeypatch.setattr(git_config_guard, "snapshot", failing)

    async def run(**kw):
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "_run", run)
    result = await terminal_exec.run("true", cwd=ws, sandbox=True)
    assert "couldn't check what git will run or load" in result["git_config_note"]
    assert "git_config permission" not in result["git_config_note"]
