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


# ── the profile ──────────────────────────────────────────────────────────────

CONFIG_REGEXES = [run_later.pattern_regex(p) for p in run_later.GIT_CONFIG]


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if "[Gg][Ii][Tt]" in line or "[Hh][Uu][Ss][Kk][Yy]" in line]


def test_the_grant_leaves_out_the_four_config_names_and_nothing_else(tmp_path):
    held = "".join("(deny file-write* " + " ".join(f) + ")\n" for f in run_later.kernel_filters([tmp_path]))
    lifted = "".join("(deny file-write* " + " ".join(f) + ")\n"
                     for f in run_later.kernel_filters([tmp_path], git_config_ok=True))
    assert held == KERNEL_TEXT
    for regex in CONFIG_REGEXES:
        assert f'(regex #"{regex}")' in held and f'(regex #"{regex}")' not in lifted
    expected = held
    for regex in CONFIG_REGEXES:
        expected = expected.replace(f' (require-all (regex #"{regex}") {DEPENDENCY_TEXT})', "")
    assert lifted == expected and expected != held
    # The hooks, .gitmodules and every other family stay.
    for pattern in (".git/hooks/**", ".git/modules/*/hooks/**", ".gitmodules", ".envrc", ".husky/**",
                    ".vscode/settings.json", ".npmrc", ".claude/settings*.json"):
        assert run_later.pattern_regex(pattern) in lifted


def test_only_the_commands_profile_takes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    (tmp_path / "home" / "ws").mkdir(parents=True)
    ws = tmp_path / "home" / "ws"
    granted = command_sandbox.commands_profile(ws, git_config_ok=True)
    assert all(f'(regex #"{r}")' not in granted for r in CONFIG_REGEXES)
    assert all(f'(regex #"{r}")' in command_sandbox.commands_profile(ws) for r in CONFIG_REGEXES)
    # The outside floor and the MCP preset have no such parameter: they always hold them.
    floor = command_sandbox.minimal_profile(run_later_in=ws)
    mcp = capability_sandbox.profile(root=tmp_path / "home" / "mcp", folders=[str(ws)], network=False, read=[])
    assert all(f'(regex #"{r}")' in floor and f'(regex #"{r}")' in mcp for r in CONFIG_REGEXES)
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
    result = await tool_loop._dispatch_tool(
        "run_command", args, "{}", resolve_tools=resolve, emit=lambda e: None, tool_timeout_s=5, tool_trace=[],
        convo=[], confirm_command=command_confirm.Confirmations(cid).command if cards else None, conversation_id=cid)
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
