"""HR-1b (v0.1.64): git may update a repository's config under this conversation's git_config grant, and what is off
the allowlist is put back after the command.

- The allowlist (server/services/git_config_guard.py): each allowed key is kept, each named program key is put back;
  section and variable names fold case, a subsection is kept verbatim.
- The revert, with real git and no sandbox: the pre-run bytes with only the allowlisted changes replayed; a new
  repository keeps git's own file minus what is off the allowlist; a parse or replay failure restores the pre-run
  bytes whole; the message names keys, never a value. The walk is bounded and fails closed.
- The profile: `git_config_ok` leaves the four config names out of the commands profile's denies and nothing else;
  the outside floor and the MCP preset never get it. git's sample hooks are exempt in both forms.
- The gate: one card per conversation, offered for this conversation only; a second command needs none; another
  conversation doesn't get it; the island never answers it; with nobody to ask it is refused and listed in the Inbox;
  `never_auto` holds for the kind.
- git's notes: a refusal on the repository config only offers the grant; `.git` is a whole path component.

The real-seatbelt cases are in tests/server/sbx/test_hr1b_git_config_kernel.py. Stand-in names only; the adversarial
config shapes are Codex's corpus.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from server.db import session as db_session
from server.orchestrator import command_gate, tool_loop
from server.orchestrator.turn_state import ToolTurn
from server.services import (approvals, capability_sandbox, command_confirm, command_sandbox, git_config_guard,
                             hard_rules, permission_store, permissions, run_later, terminal_exec)
from tests.server.test_hr1_run_later import DEPENDENCY_TEXT, KERNEL_TEXT, _by_regex, _explained, _git_noted

STAND_IN = "zz-stand-in-word"
VALUE = f"{STAND_IN}-value"          # a value that must never reach the message

# ── the allowlist ────────────────────────────────────────────────────────────

ALLOWED_KEYS = ["remote.origin.url", "remote.origin.fetch", "remote.origin.pushurl", "branch.main.remote",
                "branch.main.merge", "branch.main.rebase", "user.name", "user.email", "core.repositoryformatversion",
                "core.filemode", "core.bare", "core.logallrefupdates", "core.ignorecase", "core.precomposeunicode",
                "init.defaultbranch", f"submodule.{STAND_IN}.url", f"submodule.{STAND_IN}.active", "pull.rebase",
                "push.default"]
PROGRAM_KEYS = ["core.hookspath", "core.fsmonitor", "core.sshcommand", "core.pager", "core.editor",
                f"filter.{STAND_IN}.clean", "diff.external", f"alias.{STAND_IN}", "credential.helper", "include.path",
                f"includeif.gitdir:{STAND_IN}/.path", f"url.{STAND_IN}.insteadof"]


@pytest.mark.parametrize("key", ALLOWED_KEYS)
def test_each_allowed_key_is_kept(key):
    assert git_config_guard.allowed(key)


@pytest.mark.parametrize("key", PROGRAM_KEYS)
def test_each_named_program_key_is_put_back(key):
    assert not git_config_guard.allowed(key)


def test_section_and_variable_names_fold_case_and_a_subsection_is_verbatim():
    assert git_config_guard.allowed("Remote.Or.ig.URL") and git_config_guard.allowed("CORE.Bare")
    assert not git_config_guard.allowed("CORE.HooksPath")
    assert git_config_guard.split_key(f"Remote.{STAND_IN}.Or.ig.URL") == ("remote", f"{STAND_IN}.Or.ig", "url")
    assert git_config_guard.split_key("remote.A.url") != git_config_guard.split_key("remote.a.url")
    # A subsection where none is allowed, and none where one is: neither is on the list.
    assert not git_config_guard.allowed(f"core.{STAND_IN}.bare") and not git_config_guard.allowed("remote.url")
    assert not git_config_guard.allowed(f"user.{STAND_IN}.name")


# ── the revert, with real git ────────────────────────────────────────────────

def _repo(ws: Path, name: str = "r", text: str = "") -> Path:
    config = ws / name / ".git" / "config"
    config.parent.mkdir(parents=True)
    config.write_text(text)
    return config


def _git_set(config: Path, *args: str) -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(config.parent), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull}
    assert subprocess.run(["git", "config", "--file", str(config), *args], env=env, capture_output=True).returncode == 0


def _keys(config: Path) -> dict:
    with git_config_guard.tempfile.TemporaryDirectory() as scratch:
        (Path(scratch) / "home").mkdir()
        return git_config_guard.parse(config, Path(scratch) / "home")[0]


ORIGINAL = (f"# {STAND_IN} kept by bytes\n[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
            f"[remote \"origin\"]\n\turl = ../{STAND_IN}.git\n")


def test_the_revert_writes_the_pre_run_bytes_with_only_the_allowed_changes_replayed(tmp_path):
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    saved = git_config_guard.snapshot(ws)
    assert saved.files == {config: ORIGINAL.encode()}
    _git_set(config, "core.hooksPath", VALUE)
    _git_set(config, "remote.other.url", f"../{STAND_IN}-other.git")
    _git_set(config, "user.name", STAND_IN)
    outcome = git_config_guard.restore(saved)
    assert outcome.reverted == ["core.hookspath"] and outcome.restored == [] and not outcome.unchecked
    text = config.read_text()
    assert text.startswith(ORIGINAL)                                    # the pre-run bytes, then the replays
    keys = _keys(config)
    assert ("core", None, "hookspath") not in keys
    assert keys[("remote", "other", "url")] == [f"../{STAND_IN}-other.git"]
    assert keys[("user", None, "name")] == [STAND_IN]


def test_only_allowed_changes_leave_gits_file_as_it_wrote_it(tmp_path):
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    saved = git_config_guard.snapshot(ws)
    _git_set(config, "branch.main.remote", "origin")
    written = config.read_bytes()
    outcome = git_config_guard.restore(saved)
    assert outcome.message() == "" and config.read_bytes() == written


def test_a_removed_or_changed_program_key_gets_its_pre_run_value_back(tmp_path):
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL + f"[alias]\n\t{STAND_IN} = status\n")
    saved = git_config_guard.snapshot(ws)
    _git_set(config, "--unset", f"alias.{STAND_IN}")
    _git_set(config, "core.bare", "true")
    outcome = git_config_guard.restore(saved)
    keys = _keys(config)
    assert outcome.reverted == [f"alias.{STAND_IN}"]
    assert keys[("alias", None, STAND_IN)] == ["status"] and keys[("core", None, "bare")] == ["true"]


def test_a_new_repository_keeps_gits_file_minus_what_is_off_the_allowlist(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    saved = git_config_guard.snapshot(ws)
    assert saved.files == {}
    config = _repo(ws, "fresh", "[core]\n\tbare = false\n")
    _git_set(config, "core.hooksPath", VALUE)
    _git_set(config, f"alias.{STAND_IN}", VALUE)
    outcome = git_config_guard.restore(saved)
    assert sorted(outcome.reverted) == [f"alias.{STAND_IN}", "core.hookspath"]
    assert _keys(config) == {("core", None, "bare"): ["false"]}


def test_a_parse_failure_restores_the_pre_run_bytes_whole_and_a_new_repositorys_config_goes(tmp_path):
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    saved = git_config_guard.snapshot(ws)
    config.write_text(ORIGINAL + f"[core\n\thooksPath = {VALUE}\n")               # git can't read it
    fresh = ws / "fresh" / ".git" / "config"
    fresh.parent.mkdir(parents=True)
    fresh.write_text(f"[alias\n\t{STAND_IN} = {VALUE}\n")
    outcome = git_config_guard.restore(saved)
    assert config.read_text() == ORIGINAL and not fresh.exists()
    assert sorted(outcome.restored) == [os.path.join("fresh", ".git", "config"), os.path.join("r", ".git", "config")]
    assert VALUE not in outcome.message() and "restored them as they were" in outcome.message()


def test_a_replay_failure_restores_the_pre_run_bytes_whole(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    saved = git_config_guard.snapshot(ws)
    _git_set(config, "core.hooksPath", VALUE)
    _git_set(config, "remote.other.url", STAND_IN)

    def failing(*a, **k):
        raise git_config_guard.GuardError("stand-in failure")
    monkeypatch.setattr(git_config_guard, "_set", failing)
    outcome = git_config_guard.restore(saved)
    assert config.read_text() == ORIGINAL and outcome.restored == [os.path.join("r", ".git", "config")]
    assert outcome.reverted == []


def test_a_revised_file_that_does_not_read_as_expected_is_not_written(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    saved = git_config_guard.snapshot(ws)
    _git_set(config, "core.hooksPath", VALUE)
    monkeypatch.setattr(git_config_guard, "_set", lambda *a, **k: None)     # the replay "succeeds", doing nothing
    real_parse = git_config_guard.parse
    calls = []

    def parse(path, scratch):
        calls.append(path)
        values, names = real_parse(path, scratch)
        if len(calls) == 3:                                                    # the read-back of the result
            values = {**values, ("core", None, "hookspath"): [VALUE]}
        return values, names
    monkeypatch.setattr(git_config_guard, "parse", parse)
    outcome = git_config_guard.restore(saved)
    assert config.read_text() == ORIGINAL and outcome.restored


def test_the_message_names_keys_only_and_cuts_a_long_one():
    outcome = git_config_guard.Outcome(reverted=["core.hookspath", f"alias.{'z' * 300}"])
    text = outcome.message()
    assert "core.hookspath" in text and "z" * 200 not in text and "…" in text
    assert git_config_guard.Outcome().message() == ""


def test_the_walk_finds_each_lifted_config_skips_node_modules_and_never_follows_a_link(tmp_path):
    ws = tmp_path / "ws"
    top = _repo(ws, "r")
    git = top.parent
    (git / "config.worktree").write_text("")
    (git / "worktrees" / STAND_IN).mkdir(parents=True)
    (git / "worktrees" / STAND_IN / "config.worktree").write_text("")
    (git / "modules" / STAND_IN).mkdir(parents=True)
    (git / "modules" / STAND_IN / "config").write_text("")
    (git / "hooks").mkdir()
    (git / "hooks" / "config").write_text("")                              # not a config git reads
    nested = _repo(ws / "r", f"{STAND_IN}-nested")
    _repo(ws / "node_modules", STAND_IN)
    (ws / f"{STAND_IN}-link").symlink_to(ws / "node_modules")
    assert git_config_guard.config_files(ws) == sorted([top, git / "config.worktree",
                                                        git / "worktrees" / STAND_IN / "config.worktree",
                                                        git / "modules" / STAND_IN / "config", nested])


def test_the_walk_never_opens_a_private_folder_unless_it_works_inside_one(tmp_path, monkeypatch):
    """#813 review 8, kept here: the folders the user keeps closed and the TCC home folders aren't opened (no privacy
    prompt); the profile holds the configs in them by name under the grant too. A work folder inside one is walked."""
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    kept = _repo(home, "r")
    _repo(home / "Documents", "r")
    _repo(home / f"{STAND_IN}-closed", "r")
    assert git_config_guard.config_files(home, [home / f"{STAND_IN}-closed"]) == [kept]
    saved = git_config_guard.snapshot(home, [home / f"{STAND_IN}-closed"])
    assert list(saved.files) == [kept] and git_config_guard.restore(saved).message() == ""
    inside = home / "Documents" / "r" / ".git" / "config"
    assert git_config_guard.config_files(home / "Documents") == [inside]
    text = command_sandbox.commands_profile(home, git_config_ok=True)
    assert str(home / "Documents") in text and "[Cc][Oo][Nn][Ff][Ii][Gg]" in text


def test_the_walk_is_bounded_and_an_unreadable_folder_fails_closed(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    for name in ("a", "b", "c"):
        (ws / name).mkdir(parents=True)
    monkeypatch.setattr(git_config_guard, "MAX_FOLDERS", 3)
    with pytest.raises(git_config_guard.GuardError):
        git_config_guard.snapshot(ws)
    monkeypatch.setattr(git_config_guard, "MAX_FOLDERS", 30_000)
    real = git_config_guard._entries

    def denied(folder):
        if Path(folder) == ws / "b":
            raise PermissionError(13, "Permission denied")
        return real(folder)
    monkeypatch.setattr(git_config_guard, "_entries", denied)
    with pytest.raises(git_config_guard.GuardError):
        git_config_guard.snapshot(ws)


async def test_terminal_exec_saves_runs_lifted_and_puts_back(tmp_path, monkeypatch):
    """The product path: snapshot, the lifted profile and the template-free environment, then the put-back; a snapshot
    that fails runs the command with the configs held, and says so."""
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    seen: list = []

    async def run(**kw):
        seen.append(kw.get("git_config_ok", False))
        if kw.get("git_config_ok"):
            _git_set(config, "core.hooksPath", VALUE)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "_run", run)
    result = await terminal_exec.run("true", cwd=ws, sandbox=True, git_config=True)
    assert seen == [True] and config.read_text() == ORIGINAL
    assert "core.hookspath" in result["git_config_note"] and VALUE not in result["git_config_note"]
    # Not in the sandbox: no lift, no check.
    await terminal_exec.run("true", cwd=ws, sandbox=False, git_config=True)
    assert seen == [True, False]

    def failing(folder, closed=()):
        raise git_config_guard.GuardError("stand-in")
    monkeypatch.setattr(git_config_guard, "snapshot", failing)
    result = await terminal_exec.run("true", cwd=ws, sandbox=True, git_config=True)
    assert seen == [True, False, False] and "couldn't look through" in result["git_config_note"]


async def test_a_stopped_command_is_still_put_back(tmp_path, monkeypatch):
    import asyncio
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)

    async def run(**kw):
        _git_set(config, "core.hooksPath", VALUE)
        raise asyncio.CancelledError
    monkeypatch.setattr(terminal_exec, "_run", run)
    with pytest.raises(asyncio.CancelledError):
        await terminal_exec.run("true", cwd=ws, sandbox=True, git_config=True)
    assert config.read_text() == ORIGINAL


def test_the_environment_under_the_grant_has_no_template_folder():
    assert terminal_exec.GIT_CONFIG_ENV == {"GIT_TEMPLATE_DIR": ""}


# ── review delta 2 (⓪Plan's max review) ──────────────────────────────────────

@pytest.fixture(autouse=True)
def _fresh_guard():
    git_config_guard._BASELINES.clear()
    git_config_guard.ENDED.clear()
    yield
    git_config_guard._BASELINES.clear()
    git_config_guard.ENDED.clear()


def test_the_next_snapshot_starts_from_the_last_put_back_not_the_file(tmp_path):
    """Blocker 1: a key written between two granted commands (a process the first left running) never becomes the
    next one's baseline; that command puts it back."""
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    saved = git_config_guard.snapshot(ws)
    _git_set(config, "user.name", STAND_IN)
    assert git_config_guard.restore(saved).reverted == []
    left = config.read_bytes()
    _git_set(config, "core.hooksPath", VALUE)                    # after the put-back
    again = git_config_guard.snapshot(ws)
    assert again.files == {config: left} and again.modes == {config: 0o644}
    assert git_config_guard.restore(again).reverted == ["core.hookspath"]
    assert config.read_bytes() == left


def test_a_put_back_that_cant_be_written_is_held_and_keeps_the_pre_run_baseline(tmp_path, monkeypatch):
    """Blocker 2, fail closed: still refused after the flags and ACL are cleared, the config is `held`, the message
    says the grant ended, and the next snapshot takes the pre-run bytes, not what survived."""
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    saved = git_config_guard.snapshot(ws)
    _git_set(config, "core.hooksPath", VALUE)

    def refused(*a, **k):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(git_config_guard, "_replace", refused)
    outcome = git_config_guard.restore(saved)
    assert outcome.held == [os.path.join("r", ".git", "config")] and outcome.reverted == []
    assert git_config_guard.HELD_NOTE in outcome.message() and VALUE not in outcome.message()
    assert git_config_guard.snapshot(ws).files == {config: ORIGINAL.encode()}


def test_a_put_back_that_raises_is_held_too(monkeypatch):
    def broken(saved):
        raise OSError(5, "Input/output error")
    monkeypatch.setattr(git_config_guard, "restore", broken)
    assert terminal_exec._put_back(None) == (git_config_guard.HELD_NOTE, True)


@pytest.mark.skipif(not hasattr(os, "lchflags"), reason="file flags are BSD's")
@pytest.mark.parametrize("lock", ["uchg", "acl", "folder uchg"])
def test_a_flag_or_acl_on_the_config_or_its_folder_is_cleared_before_the_put_back(tmp_path, lock):
    """Blocker 2: the put-back's own write isn't blocked by a flag or ACL set after the key was added; the pre-run
    mode is written too."""
    import stat as st
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    saved = git_config_guard.snapshot(ws)
    _git_set(config, "core.hooksPath", VALUE)
    config.chmod(0o600)
    target = config.parent if lock == "folder uchg" else config
    if lock == "acl":
        assert subprocess.run(["/bin/chmod", "+a", "everyone deny delete", str(config)]).returncode == 0
    else:
        os.chflags(target, st.UF_IMMUTABLE)
    try:
        outcome = git_config_guard.restore(saved)
    finally:
        os.lchflags(target, 0)
    assert (outcome.reverted, outcome.held) == (["core.hookspath"], [])
    assert config.read_text() == ORIGINAL and st.S_IMODE(config.stat().st_mode) == 0o644
    assert config.stat().st_flags == 0


def test_a_hard_linked_config_drops_the_lift_and_one_linked_after_is_restored_fresh(tmp_path):
    """Blocker 3 (b): a config with a second name before the command raises Linked (no lift this run); one linked
    during it is restored whole as a new file, so the other name no longer reaches it."""
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    other = tmp_path / f"{STAND_IN}-other"
    os.link(config, other)
    with pytest.raises(git_config_guard.Linked):
        git_config_guard.snapshot(ws)
    other.unlink()
    saved = git_config_guard.snapshot(ws)
    _git_set(config, "user.name", STAND_IN)
    os.link(config, other)
    outcome = git_config_guard.restore(saved)
    assert outcome.restored == [os.path.join("r", ".git", "config")] and config.read_text() == ORIGINAL
    assert config.stat().st_nlink == 1 and not os.path.samefile(config, other)


async def test_a_linked_config_runs_held_with_its_note(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    config = _repo(ws, text=ORIGINAL)
    os.link(config, tmp_path / f"{STAND_IN}-other")
    seen = []

    async def run(**kw):
        seen.append(kw.get("git_config_ok", False))
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "_run", run)
    result = await terminal_exec.run("true", cwd=ws, sandbox=True, git_config=True)
    assert seen == [False] and "a hard link" in result["git_config_note"]


async def test_a_held_put_back_ends_the_grant_in_this_process_and_in_the_store(execution_db, gate, monkeypatch,
                                                                                 tmp_path):
    """Blocker 2, fail closed: terminal_exec marks the conversation ended; the tool loop deletes its stored grant;
    from then on its commands run held, and the flag is refused."""
    from server.services import tool_outputs
    ws = tmp_path

    async def run(**kw):
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "_run", run)
    monkeypatch.setattr(git_config_guard, "snapshot", lambda folder, closed=(): git_config_guard.Snapshot(ws, {}))
    monkeypatch.setattr(git_config_guard, "restore",
                        lambda saved: git_config_guard.Outcome(held=[os.path.join("r", ".git", "config")]))
    asker = _Asker()
    with permissions.asking_with(asker):
        assert (await _dispatch(monkeypatch, ASK, "c1"))[0] == [True]
        token = tool_outputs.conversation.set("c1")
        try:
            result = await terminal_exec.run("true", cwd=ws, sandbox=True, git_config=True)
        finally:
            tool_outputs.conversation.reset(token)
        assert result["git_config_held"] is True and "c1" in git_config_guard.ENDED
        git_config_guard.ENDED.clear()
        # The tool loop, given that result: the stored grant goes, and the conversation is ended here too.
        held = _Exec()

        async def execute(args):
            held.seen.append(terminal_exec.GIT_CONFIG.get())
            return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace",
                    "git_config_held": True}
        held.execute = execute
        monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", held)

        async def resolve():
            return [{"key": "run_command", "description": "run"}]
        await tool_loop._run_tool(
            "run_command", {"command": "git status"}, "{}", ToolTurn(resolve_tools=resolve, emit=lambda e: None,
            tool_timeout_s=5, tool_trace=[], convo=[], confirm_command=command_confirm.Confirmations("c1").command,
            conversation_id="c1"))
        assert held.seen == [True] and "c1" in git_config_guard.ENDED
        async with db_session.AsyncSessionLocal() as db:
            assert await permission_store.find_grant(db, "c1", None, "git_config", "*") is None
        assert (await _dispatch(monkeypatch, {"command": "git status"}, "c1"))[0] == [False]
        seen, refused = await _dispatch(monkeypatch, ASK, "c1")
        assert seen == [] and "git_config ended" in refused["error"] and len(asker.frames) == 1


@pytest.mark.parametrize("hooks", [".git/hooks", f".git/modules/{STAND_IN}/hooks"])
def test_a_hard_linked_file_at_a_hook_name_is_an_alias(tmp_path, hooks):
    """Blocker 5: a hook enabled by hard-linking its sample makes both names aliases, as a link there is; the sample
    exemption is off. A sample with one name isn't one."""
    ws = tmp_path / "ws"
    folder = ws / hooks
    folder.mkdir(parents=True)
    (folder / "pre-commit.sample").write_text("#!/bin/sh\n")
    assert run_later.held_folders([ws]).aliases == ()
    os.link(folder / "pre-commit.sample", folder / "pre-commit")
    aliases = run_later.held_folders([ws]).aliases
    assert sorted(p.name for p in aliases) == ["pre-commit", "pre-commit.sample"]
    assert command_sandbox.run_later_folders([ws]).aliased


# ── the profile ──────────────────────────────────────────────────────────────

CONFIG_REGEXES = [run_later.pattern_regex(p) for p in run_later.GIT_CONFIG]


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if "[Gg][Ii][Tt]" in line or "[Hh][Uu][Ss][Kk][Yy]" in line]


def _kernel_text(folder: Path, **kw) -> str:
    return "".join("(deny file-write* " + " ".join(f) + ")\n" for f in run_later.kernel_filters([folder], **kw))


def _unwalked(folder: Path, *, dependency: bool) -> str:
    """Review delta 2 (blocker 4): where git_config_guard's walk doesn't look, so the grant leaves a config held."""
    from server.services.sandbox_profile import real, regex, subpath
    terms = [f"(require-all (require-not {subpath(real(folder))}))", regex(run_later._NESTED_GIT)]
    return f"(require-any {' '.join(terms + ([regex(run_later.dependency_regex())] if dependency else []))})"


def test_the_grant_lifts_the_four_config_names_only_where_the_walk_looks_and_nothing_else(tmp_path):
    """Inside the work folder, not under a `.git` folder's own folders, and, on a profile that holds dependency
    folders (an alias was found), not under one either: exactly where git_config_guard's walk finds a config."""
    held, lifted = _kernel_text(tmp_path), _kernel_text(tmp_path, git_config_ok=True)
    assert held == KERNEL_TEXT
    expected = held
    for regex in CONFIG_REGEXES:
        assert f'(require-all (regex #"{regex}") {DEPENDENCY_TEXT})' in held
        expected = expected.replace(f'(require-all (regex #"{regex}") {DEPENDENCY_TEXT})',
                                    f'(require-all (regex #"{regex}") {_unwalked(tmp_path, dependency=False)} '
                                    f'{DEPENDENCY_TEXT})')
    assert lifted == expected and expected != held
    aliased, aliased_lifted = _kernel_text(tmp_path, aliased=True), _kernel_text(tmp_path, aliased=True,
                                                                                 git_config_ok=True)
    expected = aliased
    for regex in CONFIG_REGEXES:
        assert aliased.count(f'(regex #"{regex}")') == 1
        expected = expected.replace(f'(regex #"{regex}")',
                                    f'(require-all (regex #"{regex}") {_unwalked(tmp_path, dependency=True)})')
    assert aliased_lifted == expected and expected != aliased
    # The hooks, .gitmodules and every other family stay.
    for pattern in (".git/hooks/**", ".git/modules/*/hooks/**", ".gitmodules", ".envrc", ".husky/**",
                    ".vscode/settings.json", ".npmrc", ".claude/settings*.json"):
        assert run_later.pattern_regex(pattern) in lifted


@pytest.mark.parametrize(("path", "walked"), [
    (".git/config", True), (f"{STAND_IN}/.git/modules/{STAND_IN}/config", True),
    (f".git/{STAND_IN}/.git/config", False), (f".git/modules/{STAND_IN}/.git/config", False),
    (f"node_modules/{STAND_IN}/.git/config", False)])
def test_the_lift_and_the_walk_agree(tmp_path, path, walked):
    """The nested-`.git` and dependency terms are the walk's own skips: a config there is held and never walked."""
    import re
    ws = tmp_path / "ws"
    target = ws / path
    target.parent.mkdir(parents=True)
    target.write_text("")
    real_path = os.path.realpath(target)
    held_by_a_term = bool(re.fullmatch(run_later._NESTED_GIT, real_path)
                          or re.fullmatch(run_later.dependency_regex(), real_path))
    assert (target in git_config_guard.config_files(ws), held_by_a_term) == (walked, not walked)


def test_only_the_commands_profile_takes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "home" / "ws").mkdir(parents=True)
    ws = tmp_path / "home" / "ws"
    granted, held = command_sandbox.commands_profile(ws, git_config_ok=True), command_sandbox.commands_profile(ws)
    assert all(f'(require-all (regex #"{r}") (require-any ' in granted for r in CONFIG_REGEXES)
    assert all(f'(require-all (regex #"{r}") (require-any ' not in held for r in CONFIG_REGEXES)
    # Review delta 2 (blockers 2 and 3): even lifted, no hard link, file flag or ACL on a config.
    links = "(deny file-link file-write-flags file-write-acl " + " ".join(run_later.git_config_filters()) + ")"
    assert links in granted and "file-link" not in held
    # The outside floor and the MCP preset have no such parameter: they always hold them.
    floor = command_sandbox.minimal_profile(run_later_in=ws)
    mcp = capability_sandbox.profile(root=tmp_path / "home" / "mcp", folders=[str(ws)], network=False, read=[])
    assert all(f'(regex #"{r}")' in floor and f'(regex #"{r}")' in mcp for r in CONFIG_REGEXES)
    assert "(require-any (require-all (require-not" not in floor + mcp
    import inspect
    assert "git_config_ok" not in inspect.signature(command_sandbox.minimal_profile).parameters
    assert "git_config_ok" not in inspect.signature(capability_sandbox.profile).parameters


SAMPLE_EXEMPT = [f"/w/.git/hooks/{STAND_IN}.sample", "/w/.git/hooks/pre-commit.sample", "/w/a/.git/hooks/.sample",
                 f"/w/.git/modules/{STAND_IN}/hooks/pre-push.sample", "/w/.GIT/HOOKS/pre-commit.SAMPLE"]
SAMPLE_HELD = ["/w/.git/hooks/pre-commit", f"/w/.git/hooks/{STAND_IN}", "/w/.git/hooks",
               f"/w/.git/hooks/{STAND_IN}.sample.d/pre-commit", f"/w/.git/hooks/{STAND_IN}.sample-{STAND_IN}",
               f"/w/.git/hooks/{STAND_IN}.samples", f"/w/.git/hooks/sub/{STAND_IN}.sample",
               f"/w/.git/modules/{STAND_IN}/hooks/{STAND_IN}"]


@pytest.mark.parametrize("path", SAMPLE_EXEMPT)
def test_a_sample_hook_is_exempt_in_both_forms(path):
    assert not run_later.matches(path) and not _by_regex(path)


@pytest.mark.parametrize("path", SAMPLE_HELD)
def test_an_exact_hook_name_or_a_name_only_containing_sample_stays_held_in_both_forms(path):
    assert run_later.family(path) == "git" and _by_regex(path)


@pytest.mark.parametrize("link, to", [(".git/hooks/pre-commit", "pre-commit.sample"),
                                      (".git/hooks/pre-commit", f"../../{STAND_IN}"),
                                      (f".git/modules/{STAND_IN}/hooks/pre-push", "pre-push.sample"),
                                      (".git/hooks", f"../{STAND_IN}-hooks")])
def test_a_link_at_a_hook_name_is_an_alias_and_the_profile_drops_the_sample_exemption(tmp_path, link, to):
    """⓪Plan's ruling: a link at a hook name (any name in a hooks folder), or a hooks folder that is a link, is an
    alias wherever it points (inside its own folder too), a submodule's one level under `.git/modules` included:
    `aliased` holds, and the profile writes the hooks names with neither exemption. A link at an ordinary name
    outside the hooks folder, to a sample, is not one."""
    sample = "[Ss][Aa][Mm][Pp][Ll][Ee]"

    def denies(text: str) -> str:
        return "".join(line for line in text.splitlines() if line.startswith("(deny file-write* "))
    ws = tmp_path / "ws"
    (ws / ".git" / "modules" / STAND_IN / "hooks").mkdir(parents=True)
    (ws / ".git" / "hooks").mkdir()
    at = ws / link
    if at.is_dir():
        at.rmdir()
    at.symlink_to(to)
    hold = command_sandbox.run_later_folders([ws])
    assert [p.name for p in hold.aliases] == [at.name] and hold.aliased
    assert sample not in denies(command_sandbox.commands_profile(ws))
    plain = tmp_path / "plain"
    (plain / ".git" / "hooks").mkdir(parents=True)
    (plain / f"{STAND_IN}-note").symlink_to(".git/hooks/pre-commit.sample")
    assert run_later.held_folders([plain]).aliases == ()
    assert sample in denies(command_sandbox.commands_profile(plain))


def test_the_file_tools_keep_the_config_names_whatever_the_grant():
    assert all(run_later.matches(f"/w/{p.replace('*', STAND_IN)}") for p in run_later.GIT_CONFIG)
    assert all(run_later.is_git_config(f"/w/{p.replace('*', STAND_IN)}") for p in run_later.GIT_CONFIG)
    assert not run_later.is_git_config("/w/.git/hooks/pre-commit") and not run_later.is_git_config("/w/.gitmodules")


# ── the gate ─────────────────────────────────────────────────────────────────

@pytest.fixture
def gate(monkeypatch):
    command_sandbox._reset_for_tests()
    permissions._reset_for_tests()
    approvals._reset_for_tests()

    async def answer(value):
        return value
    monkeypatch.setattr(command_gate, "_asks_for_everything", lambda: answer(False))
    monkeypatch.setattr(command_gate, "_sandbox_enabled", lambda: answer(True))
    monkeypatch.setattr(command_gate, "_work_folder_holds_home", lambda: answer(False))
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    yield
    command_sandbox._reset_for_tests()
    permissions._reset_for_tests()
    approvals._reset_for_tests()


class _Asker:
    def __init__(self, approved=True, scope="conversation", by="mac"):
        self.frames: list[dict] = []
        self.reply = {"approved": approved, "scope": scope, "note": "", "by": by}

    async def __call__(self, frame):
        self.frames.append(frame)
        return {**self.reply, "call_id": frame["call_id"]}


class _Exec:
    key = "run_command"

    def __init__(self):
        self.seen: list[bool] = []

    async def execute(self, args):
        self.seen.append(terminal_exec.GIT_CONFIG.get())
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}


async def _dispatch(monkeypatch, args, cid, *, cards=True):
    ex = _Exec()
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", ex)

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    result = await tool_loop._run_tool(
        "run_command", args, "{}", ToolTurn(resolve_tools=resolve, emit=lambda e: None, tool_timeout_s=5, tool_trace=[],
        convo=[], confirm_command=command_confirm.Confirmations(cid).command if cards else None, conversation_id=cid))
    return ex.seen, result


async def _rows():
    async with db_session.AsyncSessionLocal() as db:
        return list(reversed(await permission_store.recent(db)))


ASK = {"command": "git status", "git_config": True, "why": f"{STAND_IN} needs an upstream"}


async def test_the_card_asks_once_per_conversation_and_never_leaks_to_another(execution_db, gate, monkeypatch):
    asker = _Asker()
    with permissions.asking_with(asker):
        seen, _ = await _dispatch(monkeypatch, ASK, "c1")
        assert seen == [True] and len(asker.frames) == 1
        frame = asker.frames[0]
        assert (frame["perm_kind"], frame["options"], frame["type"]) == ("git_config", ["conversation"],
                                                                        "propose_action")
        assert frame["title"] == "Let git update this repository's settings?" and frame["why"] == ASK["why"]
        # A second command in the same conversation: no card, with the flag or without it.
        assert (await _dispatch(monkeypatch, ASK, "c1"))[0] == [True]
        assert (await _dispatch(monkeypatch, {"command": "git status"}, "c1"))[0] == [True]
        assert len(asker.frames) == 1
        # Another conversation: nothing without the flag, and its own card with it.
        assert (await _dispatch(monkeypatch, {"command": "git status"}, "c2"))[0] == [False]
        assert len(asker.frames) == 1
        assert (await _dispatch(monkeypatch, ASK, "c2"))[0] == [True] and len(asker.frames) == 2
    rows = [(r.kind, r.decided_by, r.decision, r.scope, r.conversation_id) for r in await _rows()
            if r.kind == "git_config"]
    assert rows == [("git_config", "user", "allow", "conversation", "c1"), ("git_config", "grant", "allow",
                    "conversation", "c1"), ("git_config", "grant", "allow", "conversation", "c1"),
                    ("git_config", "user", "allow", "conversation", "c2")]


async def test_a_no_runs_nothing_and_stores_nothing_and_a_why_is_needed(execution_db, gate, monkeypatch):
    asker = _Asker(approved=False, scope=None)
    with permissions.asking_with(asker):
        seen, result = await _dispatch(monkeypatch, ASK, "c1")
        assert seen == [] and result["ok"] is False
        seen, _ = await _dispatch(monkeypatch, {"command": "git status"}, "c1")
        assert seen == [False]
        seen, result = await _dispatch(monkeypatch, {"command": "git status", "git_config": True}, "c1")
        assert seen == [] and "needs a why" in result["error"] and len(asker.frames) == 1


async def test_outside_the_sandbox_it_is_never_asked_nor_applied(execution_db, gate, monkeypatch):
    async def answer(value):
        return value
    monkeypatch.setattr(command_gate, "_sandbox_enabled", lambda: answer(False))
    asker = _Asker()
    with permissions.asking_with(asker):
        seen, _ = await _dispatch(monkeypatch, ASK, "c1")
    assert all(f.get("perm_kind") != "git_config" for f in asker.frames)
    assert seen in ([], [False])


async def test_with_nobody_to_ask_it_is_refused_and_listed_in_the_inbox(execution_db, gate):
    refused = await command_gate._git_config(ASK, "c1")
    assert isinstance(refused, dict) and refused["ok"] is False and "nobody to ask" in refused["error"]
    rows = [(r.kind, r.decided_by, r.decision) for r in await _rows()]
    assert rows == [("git_config", "policy", "deny")]
    async with db_session.AsyncSessionLocal() as db:
        listed = await permission_store.refused_groups(db, datetime.utcnow() - timedelta(hours=1))
    assert [(row.kind, count) for row, count, _ in listed] == [("git_config", 1)]


def test_the_island_never_answers_it_and_it_is_never_auto():
    frame = {"type": "propose_action", "call_id": "x", "perm_kind": "git_config", "kind": "git_config"}
    assert not approvals.island_may_answer(frame)
    request = permissions.Request(kind="git_config", target="/w", title="t")
    assert hard_rules.never_auto(request) and "git_config" in hard_rules.NEVER_AUTO_KINDS
    assert permissions.options_for(request) == ["conversation"]
    assert "git_config" not in hard_rules.MAY_AUTO_KINDS


async def test_the_island_cannot_approve_its_pending_card(execution_db, gate):
    import asyncio
    with permissions.asking_with(approvals.BroadcastAsker("c1")):
        task = asyncio.ensure_future(command_gate._git_config(ASK, "c1"))
        for _ in range(50):
            await asyncio.sleep(0.01)
            pending = [p for p in approvals.all_pending() if p["frame"].get("perm_kind") == "git_config"]
            if pending:
                break
        assert pending and pending[0]["island_ok"] is False
        with pytest.raises(approvals.OpenInArslan):
            approvals.answer_by_id(pending[0]["call_id"], True, source="island")
        approvals.answer_by_id(pending[0]["call_id"], False, source="island")
        assert isinstance(await task, dict)


# ── git's notes ──────────────────────────────────────────────────────────────

CONFIG_REFUSED = "error: could not write config file .git/config: Operation not permitted\n"
HOOK_REFUSED = f"error: unable to create file .git/hooks/{STAND_IN}: Operation not permitted\n"
GITMODULES_REFUSED = "error: could not lock config file .gitmodules: Operation not permitted\n"


def test_a_config_only_refusal_offers_the_grant_and_nothing_else_does(tmp_path, monkeypatch):
    offered = command_sandbox.git_note(git_config=True)
    for exit_code in (0, 128):
        result, _, _ = _explained(tmp_path, monkeypatch, exit_code=exit_code, stderr=CONFIG_REFUSED,
                                  command="git push -u origin x")
        assert "git_config: true" in result["note"]
    assert _explained(tmp_path, monkeypatch, exit_code=0, stderr=CONFIG_REFUSED)[0]["note"] == offered
    for line in (HOOK_REFUSED, CONFIG_REFUSED + HOOK_REFUSED, GITMODULES_REFUSED):
        assert "git_config" not in _explained(tmp_path, monkeypatch, exit_code=0, stderr=line)[0]["note"]
    # Under the outside floor: the floor never lifts them, so nothing is offered.
    floor, _, _ = _explained(tmp_path, monkeypatch, exit_code=0, stderr=CONFIG_REFUSED, sandbox="outside", hold=True)
    assert floor["note"] == command_sandbox.git_note()


def test_under_the_grant_a_config_refusal_does_not_offer_it_again(tmp_path):
    result = {"ok": True, "exit_code": 0, "stdout": "", "stderr": CONFIG_REFUSED, "cwd": str(tmp_path),
              "sandbox": "workspace"}
    terminal_exec.explain(result, cwd=tmp_path, closed=[], mode="workspace", timed_out=False, command="git status",
                          git_config=True)
    assert result["note"] == command_sandbox.git_note()


def test_a_gitmodules_refusal_at_a_non_zero_exit_gets_the_git_note_not_the_stop_note(tmp_path, monkeypatch):
    """`.gitmodules` is a work-tree file, not inside `.git`: `git_setup_failed` takes `.git` as a whole path component,
    never as a substring, so a failed `submodule add` reads as a partly updated tree."""
    explained = _explained(tmp_path, monkeypatch, exit_code=128, stderr=GITMODULES_REFUSED,
                           command=f"git submodule add ../{STAND_IN}.git")
    assert _git_noted(explained) and explained[0]["sandbox_denied"] is True
    assert command_sandbox.git_setup_failed({"ok": False}, [".git/config", "x/.GIT/hooks/y"])
    assert not command_sandbox.git_setup_failed({"ok": False}, [".gitmodules"])
    assert not command_sandbox.git_setup_failed({"ok": False}, [f"{STAND_IN}.git/config"])
