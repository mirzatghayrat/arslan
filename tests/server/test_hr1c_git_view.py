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
    monkeypatch.setattr(git_config_guard, "UNRESOLVED", {})
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
async def test_git_failing_or_timing_out_refuses_the_command(ws, monkeypatch, how):
    """Review delta 1 (G2): an incomplete snapshot is not a note: the command doesn't start, and the step says why."""
    git = _init(ws / "r")
    if how == "timeout":
        monkeypatch.setattr(git_config_guard, "VIEW_TIMEOUT_S", 0)
    else:
        monkeypatch.setattr(git_config_guard, "_SANDBOX_EXEC", str(ws / f"{STAND_IN}-missing"))
    saved = _snap(ws)
    assert saved.repos == {git: None} and git_config_guard.incomplete(saved) == {ws / "r": "git couldn't answer for it"}
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    ran = _fake_run(monkeypatch)
    result = await terminal_exec.run("true", cwd=ws, sandbox=True)
    assert ran == [] and result["code"] == "git_unchecked" and not result["ok"]
    assert "git couldn't answer for it" in result["git_config_note"] and str(ws / "r") in result["git_config_note"]


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
def test_a_commondir_changed_to_outside_is_named_and_the_next_command_there_is_refused(ws, tmp_path):
    git = _init(ws / "r")
    elsewhere = _init(tmp_path / f"{STAND_IN}.git", "--bare")
    saved = _snap(ws)
    (git / "commondir").write_text(f"{elsewhere}\n")
    outcome = git_config_guard.restore(saved)
    assert outcome.moved == [os.path.join("r", ".git")] and "r/.git" in outcome.message()
    assert list(outcome.unresolved) == [ws / "r"] and "refuses the next command" in outcome.message()
    git_config_guard.keep_unresolved(outcome.unresolved, saved)
    with pytest.raises(git_config_guard.Refused, match="moved outside the working folder"):
        git_config_guard.resolve("git status", ws / "r")


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


async def test_a_folder_that_cant_be_walked_is_refused_and_says_so(ws, monkeypatch):
    """Review delta 1 (G2), flipped: it used to run with a note."""
    monkeypatch.setattr(command_sandbox, "available", lambda: True)

    def failing(folder, closed=(), **kw):
        raise git_config_guard.GuardError("more than 3 folders to check")
    monkeypatch.setattr(git_config_guard, "snapshot", failing)
    ran = _fake_run(monkeypatch)
    result = await terminal_exec.run("true", cwd=ws, sandbox=True)
    assert ran == [] and result["code"] == "git_unchecked"
    assert "more than 3 folders" in result["git_config_note"] and "didn't run it" in result["git_config_note"]
    assert "git_config permission" not in result["git_config_note"]


# ── review delta 1 (G2): an incomplete check fails closed, per repository ────

def _fake_run(monkeypatch, effect=None) -> list:
    """terminal_exec._run replaced: each call's cwd; the first call also runs `effect` (the command's own doing)."""
    ran: list = []
    pending = [effect] if effect is not None else []

    async def run(**kw):
        ran.append(Path(kw["cwd"]))
        if pending:
            pending.pop()()
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "_run", run)
    return ran


_POPEN = subprocess.Popen


class _Proc:
    def __init__(self, out: bytes, code: int = 0, hang: bool = False):
        self.out, self.returncode, self.hang = out, code, hang

    def communicate(self, timeout=None):
        if self.hang and timeout is not None:
            raise subprocess.TimeoutExpired("git", timeout)
        return self.out, b""

    def kill(self):
        self.hang = False


class _FakeGit:
    """Stands in for git under sandbox-exec (`subprocess.Popen` in git_config_guard): answers rev-parse and config
    --list as git would for a plain repository (commondir followed), or fails as `mode` says for the repositories
    inside `only` (every one when None)."""
    def __init__(self):
        self.mode, self.only = "ok", None

    def __call__(self, argv, **kw):
        if argv[0] != git_config_guard._SANDBOX_EXEC:
            return _POPEN(argv, **kw)                             # HR-1b's `config --file` runs (subprocess.run)
        given = Path(next(a for a in argv if a.startswith("--git-dir=")).split("=", 1)[1])
        mode = self.mode if self.only is None or self.only == given or self.only in given.parents else "ok"
        git = Path(os.path.realpath(given))
        if git.is_file():                                         # a linked worktree's `.git` file
            git = Path(os.path.realpath(git.parent / git.read_text().split(":", 1)[1].strip()))
        if mode == "launch":
            raise OSError(2, "stand-in: not started")
        listing = "--list" in argv
        if mode == "nonzero" or (mode == "include-error" and listing):
            return _Proc(b"", 128)
        if mode == "timeout":
            return _Proc(b"", hang=True)
        if mode == "malformed":
            return _Proc(b"stand-in\0" if listing else b"stand-in\n")
        if listing:
            return _Proc(b"")
        common = Path(os.path.realpath(git / (git / "commondir").read_text().strip())) \
            if (git / "commondir").exists() else git
        return _Proc(f"{git}\n{common}\n{common / 'hooks'}\n".encode())


@pytest.fixture
def g2(ws, monkeypatch):
    """Two repositories in the work folder (git folders only, no git run), the fake git, D on."""
    for name in ("r1", "r2"):
        (_git_folder(ws / name / ".git") / "config").write_text("[core]\n\tbare = false\n")
    fake = _FakeGit()
    monkeypatch.setattr(git_config_guard.subprocess, "Popen", fake)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(git_config_guard, "UNRESOLVED", {})
    return fake


GIT_FAILURES = ["launch", "nonzero", "timeout", "malformed", "include-error"]


@pytest.mark.parametrize("mode", GIT_FAILURES)
async def test_g2_git_failing_before_the_command_refuses_it_and_only_there(ws, g2, monkeypatch, mode):
    ran = _fake_run(monkeypatch)
    g2.mode = mode
    result = await terminal_exec.run("true", cwd=ws / "r1", sandbox=True)
    assert ran == [] and result["code"] == "git_unchecked" and str(ws / "r1") in result["git_config_note"]
    assert git_config_guard.UNRESOLVED == {}                     # nothing ran: the next command checks afresh
    g2.mode = "ok"
    assert (await terminal_exec.run("true", cwd=ws / "r1", sandbox=True))["ok"] and ran == [ws / "r1"]


def _commondir_outside(ws: Path) -> None:
    (ws / "r1" / ".git" / "commondir").write_text(f"{_git_folder(ws.parent / f'{STAND_IN}-common')}\n")


POST_FAILURES = [*GIT_FAILURES, "walk", "identity", "repair", "re-survey", "quarantine", "check"]


@pytest.mark.parametrize("what", POST_FAILURES)
async def test_g2_a_check_after_the_command_that_cant_finish_refuses_the_next_command_there(ws, g2, monkeypatch,
                                                                                               what):
    """Each incomplete path after the command: that repository's next command is refused, `git -C` from elsewhere
    too; the healthy repository beside it and a folder with no repository run, the failure still in place for r1."""
    r1 = ws / "r1"
    config = r1 / ".git" / "config"

    def effect():
        if what in GIT_FAILURES:
            g2.mode, g2.only = what, r1
        elif what == "walk":
            _in_r1(monkeypatch, r1, "_walk", lambda folder, *a: folder,
                   git_config_guard.GuardError("more than 30000 folders to check"))
        elif what == "identity":
            _commondir_outside(ws)
        elif what in ("repair", "re-survey"):
            config.write_text(f"[core]\n\tbare = false\n\thooksPath = {STAND_IN}\n")     # through another name
            if what == "repair":
                _in_r1(monkeypatch, r1, "_replace", lambda path, *a: path, PermissionError(1, "Operation not permitted"))
            else:
                # The check after the command asks once (before the put-back), then fails when asked again.
                _in_r1(monkeypatch, r1, "_survey", lambda repos: repos[0] if repos else Path("/"),
                       git_config_guard.GuardError("stand-in: git couldn't be asked"), after=1)
        elif what == "quarantine":
            _hook(r1 / ".git" / "hooks")
            _in_r1(monkeypatch, r1, "_quarantine", lambda path, box: path, PermissionError(1, "Operation not permitted"))
        else:
            _in_r1(monkeypatch, r1, "restore", lambda saved, *a: saved.folder, OSError(5, "Input/output error"))
    ran = _fake_run(monkeypatch, effect)
    result = await terminal_exec.run("true", cwd=ws / "r1", sandbox=True)
    # Review delta 2: a repository's mark is also kept under its git common folder (the work folder here is r1's top,
    # so a folder mark from the walk or the whole check gets it too).
    common = {ws / "r1" / ".git"}
    assert ran == [ws / "r1"] and set(git_config_guard.UNRESOLVED) == {ws / "r1"} | common, result.get("git_config_note")
    if what != "check":
        assert "refuses the next command" in result["git_config_note"]
    ran.clear()
    for command, cwd in (("git status", ws / "r1"), ("git -C ../r1 status", ws / "r2"), (f"ls {ws}", ws.parent)):
        refused = await terminal_exec.run(command, cwd=cwd, sandbox=True)
        assert refused["code"] == "git_unchecked" and str(ws / "r1") in refused["git_config_note"], command
    assert ran == []
    for cwd in (ws / "r2", ws.parent / f"{STAND_IN}-elsewhere"):
        cwd.mkdir(exist_ok=True)
        assert (await terminal_exec.run("true", cwd=cwd, sandbox=True))["ok"]
    assert ran == [ws / "r2", ws.parent / f"{STAND_IN}-elsewhere"]
    assert set(git_config_guard.UNRESOLVED) == {ws / "r1"} | common


_RESTORE = git_config_guard.restore


def _refused(*a, **k):
    raise PermissionError(1, "Operation not permitted")


def _in_r1(monkeypatch, r1: Path, name: str, where, error: BaseException, after: int = 0) -> None:
    """`git_config_guard.<name>` fails with `error` when `where(args)` is inside r1, after `after` such calls; it
    works as before everywhere else."""
    real, count = getattr(git_config_guard, name), [0]

    def failing(*args, **kw):
        if r1 in Path(os.path.realpath(where(*args))).parents or Path(os.path.realpath(where(*args))) == r1:
            count[0] += 1
            if count[0] > after:
                raise error
        return real(*args, **kw)
    monkeypatch.setattr(git_config_guard, name, failing)


async def test_g2_the_repository_stays_refused_until_a_full_check_succeeds_against_the_last_complete_one(
        ws, tmp_path, g2, monkeypatch):
    """Refused on every command while the check can't finish; then it runs, and what the unfinished check missed (a
    hook written during that command) is quarantined, not adopted as the starting point."""
    def effect():
        _hook(ws / "r1" / ".git" / "hooks")
        monkeypatch.setattr(git_config_guard, "restore", _refused)               # the check after it fails
    ran = _fake_run(monkeypatch, effect)
    await terminal_exec.run("true", cwd=ws / "r1", sandbox=True)
    _fake_run(monkeypatch)
    for _ in range(3):
        assert (await terminal_exec.run("true", cwd=ws / "r1", sandbox=True))["code"] == "git_unchecked"
    assert (ws / "r1" / ".git" / "hooks" / "pre-commit").exists()
    assert set(git_config_guard.UNRESOLVED) == {ws / "r1", ws / "r1" / ".git"}
    monkeypatch.setattr(git_config_guard, "restore", _RESTORE)                    # a full check can succeed now
    result = await terminal_exec.run("true", cwd=ws / "r1", sandbox=True)
    assert result["ok"] and "pre-commit" in result["git_config_note"] and git_config_guard.UNRESOLVED == {}
    assert not (ws / "r1" / ".git" / "hooks" / "pre-commit").exists() and _quarantined(tmp_path) == ["pre-commit"]
    assert ran == [ws / "r1"]


_WALK = git_config_guard._walk


async def test_g2_a_repository_mark_that_becomes_its_folders_mark_on_a_failed_recheck_still_refuses(
        ws, g2, monkeypatch):
    """Review delta 2: the command ran in the folder holding r1 and r2; r1's check didn't finish (its mark). Its
    recheck then can't walk the folder: the mark becomes the folder's, and a command in r1, or in r2 inside that
    folder, is refused; it still checks against the last complete snapshot."""
    def effect():
        g2.mode, g2.only = "timeout", ws / "r1"
    _fake_run(monkeypatch, effect)
    await terminal_exec.run("true", cwd=ws, sandbox=True)
    assert set(git_config_guard.UNRESOLVED) == {ws / "r1", ws / "r1" / ".git"}
    saved = git_config_guard.UNRESOLVED[ws / "r1"][1]
    _in_r1(monkeypatch, ws, "_walk", lambda folder, *a: folder,
           git_config_guard.GuardError("more than 30000 folders to check"))
    ran = _fake_run(monkeypatch)
    for cwd in (ws / "r1", ws / "r2"):
        refused = await terminal_exec.run("git status", cwd=cwd, sandbox=True)
        assert refused["code"] == "git_unchecked" and "looked through" in refused["git_config_note"], cwd
    assert ran == [] and set(git_config_guard.UNRESOLVED) == {ws}
    assert git_config_guard.UNRESOLVED[ws][1] is saved
    monkeypatch.setattr(git_config_guard, "_walk", _WALK)
    g2.mode = "ok"
    assert (await terminal_exec.run("git status", cwd=ws / "r1", sandbox=True))["ok"] and ran == [ws / "r1"]
    assert git_config_guard.UNRESOLVED == {}


async def test_g2_a_folder_mark_that_becomes_repository_marks_on_a_failed_recheck_still_refuses_each(
        ws, g2, monkeypatch):
    """Review delta 2: the folder couldn't be walked after the command (its mark); at the recheck it can, but git
    gives no answer for r2. A command run in the healthy r1 that reaches r2 (`git -C ../r2`) is refused by r2's new
    mark, though its own folder checks fine; then r1's own command runs, and r2's is refused."""
    _fake_run(monkeypatch, lambda: _in_r1(monkeypatch, ws, "_walk", lambda folder, *a: folder,
                                          git_config_guard.GuardError("more than 30000 folders to check")))
    await terminal_exec.run("true", cwd=ws, sandbox=True)
    assert set(git_config_guard.UNRESOLVED) == {ws}
    monkeypatch.setattr(git_config_guard, "_walk", _WALK)
    g2.mode, g2.only = "timeout", ws / "r2"
    ran = _fake_run(monkeypatch)
    refused = await terminal_exec.run("git -C ../r2 status", cwd=ws / "r1", sandbox=True)
    assert refused["code"] == "git_unchecked" and "answer" in refused["git_config_note"] and ran == []
    assert set(git_config_guard.UNRESOLVED) == {ws / "r2", ws / "r2" / ".git"}
    assert (await terminal_exec.run("true", cwd=ws / "r1", sandbox=True))["ok"] and ran == [ws / "r1"]
    assert (await terminal_exec.run("git status", cwd=ws / "r2", sandbox=True))["code"] == "git_unchecked"


async def test_g2_a_worktree_sharing_an_unresolved_repositorys_git_metadata_is_refused_too(ws, g2, monkeypatch):
    """Review delta 2: `main` and a linked worktree `wt` share one common folder (`main/.git`); main's check didn't
    finish, and a command in `wt`, which no path of main's reaches, meets the same mark."""
    main = ws / "main" / ".git"
    _git_folder(main)
    (_git_folder(main / "worktrees" / "wt") / "commondir").write_text("../..\n")
    (ws / "wt").mkdir()
    (ws / "wt" / ".git").write_text(f"gitdir: {main / 'worktrees' / 'wt'}\n")
    (main / "worktrees" / "wt" / "gitdir").write_text(f"{ws / 'wt' / '.git'}\n")

    def effect():
        g2.mode, g2.only = "timeout", main
    _fake_run(monkeypatch, effect)
    await terminal_exec.run("true", cwd=ws / "main", sandbox=True)
    assert set(git_config_guard.UNRESOLVED) == {ws / "main", main, ws / "wt"}
    ran = _fake_run(monkeypatch)
    refused = await terminal_exec.run("git status", cwd=ws / "wt", sandbox=True)
    assert refused["code"] == "git_unchecked" and ran == []
    assert (await terminal_exec.run("true", cwd=ws / "r2", sandbox=True))["ok"] and ran == [ws / "r2"]


async def test_g2_with_no_git_binary_it_is_a_note_not_a_refusal(ws, g2, monkeypatch):
    monkeypatch.setattr(git_config_guard, "_GITS", (str(ws / f"{STAND_IN}-no-git"),))
    ran = _fake_run(monkeypatch)
    result = await terminal_exec.run("true", cwd=ws / "r1", sandbox=True)
    assert result["ok"] and ran == [ws / "r1"] and "couldn't ask git" in result["git_config_note"]
    assert git_config_guard.UNRESOLVED == {}


@pytest.mark.parametrize(("command", "cwd", "reaches"), [
    ("git status", "r1", True), ("git -C ../r1 log", "r2", True), ("git --git-dir=../r1/.git log", "r2", True),
    ("cat ../r1/a.txt", "r2", True), ("ls", ".", True), ("git status", "r2", False), ("ls /usr/bin", "r2", False),
    ("echo 'unclosed", "r2", True)])
def test_what_reaches_a_repository(ws, command, cwd, reaches):
    (ws / "r1").mkdir()
    (ws / "r2").mkdir()
    assert git_config_guard.touches(ws / "r1", command, ws / cwd) is reaches
