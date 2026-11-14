"""HR-2b (v0.1.64, the user's decision of 2026-11-10): the push card names outgoing CI files, the turn's change list
marks them, and a card after a git refusal.

1. The `git push` card (layer ②, once only already) names the CI files (`run_later.is_ci_file`) the outgoing commits
   change, read by git_config_guard's pinned launcher (`_each`: pinned environment, read-only seatbelt, time limit):
   `<upstream>..HEAD`, else `<remote>/HEAD..HEAD`. A failure or timeout says Arslan couldn't list them, and the card
   still shows. No new frame key: the list goes in the frame's `reason` (the phone's text) and `summary.touches`
   (the Mac card's "touches" row).
2. `checkpoints.changes` marks each CI path (`ci: true`).
3. After git's own refusal lines named a held file in a conversation (`git_refused`), its next `git add` or `git
   commit` asks a once-only card (kind `git_refused`); the island never answers it, nobody to ask refuses it and
   lists it in the Inbox, and the user's answer clears the mark. The named risk: a commit over a half-updated tree.

Tmp repositories, a local bare repository as the remote, stand-in names; no network.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from server.db import session as db_session
from server.orchestrator import command_gate, untrusted
from server.orchestrator.turn_state import ToolTurn
from server.services import (approvals, checkpoints, command_confirm, command_sandbox, git_config_guard, hard_rules,
                             permission_store, permissions, settings_service, terminal_exec, tool_outputs)
from server.services.sandbox_profile import default_deny_profile
from tests.server.test_hr1c_git_view import _git, _init

seatbelt = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                              reason="git is asked in seatbelt, which is macOS-only")
CI, OTHER = ".github/workflows/zz-stand-in.yml", "src/zz_stand_in.py"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    permissions._reset_for_tests()
    approvals._reset_for_tests()
    monkeypatch.setattr(command_sandbox, "GIT_REFUSED_IN", set())
    yield
    permissions._reset_for_tests()
    approvals._reset_for_tests()


class _Asker:
    def __init__(self, approved=True):
        self.frames: list[dict] = []
        self.approved = approved

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": self.approved, "scope": "once" if self.approved else None, "note": "", "by": "mac",
                "call_id": frame["call_id"]}


# ── 1. the push card ─────────────────────────────────────────────────────────

def _cloned(tmp_path: Path) -> Path:
    """A clone of a local bare repository (upstream and origin/HEAD set), with one local commit changing a CI file and
    another file."""
    bare = _init(tmp_path / "remote.git", "--bare", "-b", "main")
    seed = _init(tmp_path / "seed", "-b", "main").parent
    (seed / "README").write_text("zz\n")
    _git(seed, "add", "README")
    _git(seed, "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", str(bare), "HEAD:refs/heads/main")
    _git(tmp_path, "clone", "-q", str(bare), "repo")
    return Path(os.path.realpath(tmp_path / "repo"))


def _commit(repo: Path, *paths: str) -> None:
    for rel in paths:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("zz\n")
    _git(repo, "add", *paths)
    _git(repo, "commit", "-q", "-m", "zz")


async def _push_card(monkeypatch, folder: Path | None, command: str = "git push") -> dict:
    async def run_folder():
        return folder
    monkeypatch.setattr(command_gate, "run_folder", run_folder)
    monkeypatch.setattr(settings_service, "default_permission_mode", AsyncMock(return_value="ask_risky"))
    asker = _Asker()
    with permissions.asking_with(asker):
        assert await command_confirm.Confirmations("c1").command(command, []) is True
    [frame] = asker.frames
    assert frame["type"] == "propose_run_command" and frame["rules"] == ["git-push"] and frame["options"] == ["once"]
    return frame


@pytest.mark.macos
@seatbelt
@pytest.mark.parametrize("upstream", [True, False], ids=["upstream", "remote-head"])
async def test_the_push_card_lists_an_outgoing_ci_file_and_not_another(execution_db, tmp_path, monkeypatch, upstream):
    repo = _cloned(tmp_path)
    if not upstream:
        _git(repo, "checkout", "-q", "-b", "topic")       # no upstream: read against origin/HEAD
    _commit(repo, CI, OTHER)
    frame = await _push_card(monkeypatch, repo, "git push" if upstream else "git push -u origin topic")
    assert frame["summary"]["touches"][0] == f"CI file: {CI}"
    assert CI in frame["reason"]
    assert not any(OTHER in item for item in frame["summary"]["touches"]) and OTHER not in frame["reason"]


@pytest.mark.macos
@seatbelt
async def test_a_push_with_no_ci_file_adds_nothing(execution_db, tmp_path, monkeypatch):
    repo = _cloned(tmp_path)
    _commit(repo, OTHER)
    frame = await _push_card(monkeypatch, repo)
    assert frame["reason"] == "publishes to a remote repository"
    assert not any("CI file" in item or "couldn't" in item for item in frame["summary"]["touches"])


class _Popen:
    """A stand-in for git under sandbox-exec: records each launch, then fails, times out or answers `out`. `answers`
    overrides that per launch, keyed by a substring of an argument; the upstream query (`for-each-ref`) answers
    "upstream configured" unless overridden."""

    def __init__(self, how: str, out: bytes = b"", answers: dict[str, tuple[str, bytes]] | None = None):
        self.how, self.out, self.launched = how, out, []
        self.answers = {"for-each-ref": (how, b"*refs/remotes/origin/main\n"), **(answers or {})}

    def __call__(self, argv, **kw):
        self.launched.append((argv, kw))
        how, out = next((v for k, v in self.answers.items() if any(k in a for a in argv)), (self.how, self.out))

        class _Process:
            returncode = 0 if how == "answers" else 128

            def communicate(self, timeout=None):
                if how == "times out" and timeout is not None:
                    raise subprocess.TimeoutExpired(argv, timeout)
                return out, b""

            def kill(self):
                pass
        return _Process()


@pytest.fixture
def repo_dir(tmp_path, monkeypatch) -> Path:
    """A folder with a `.git` folder (git itself is faked), and a fixed git path."""
    (tmp_path / "w" / ".git").mkdir(parents=True)
    monkeypatch.setattr(git_config_guard, "_git_binary", lambda: "/usr/bin/git")
    return Path(os.path.realpath(tmp_path / "w"))


@pytest.mark.parametrize("how", ["fails", "times out", "raises"])
async def test_a_git_failure_or_timeout_says_couldnt_list_and_the_card_still_shows(execution_db, repo_dir, monkeypatch,
                                                                                    how):
    if how == "raises":
        def broken(*_args):
            raise RuntimeError("zz")
        monkeypatch.setattr(git_config_guard, "outgoing_ci", broken)
    else:
        monkeypatch.setattr(git_config_guard.subprocess, "Popen", _Popen(how))
    frame = await _push_card(monkeypatch, repo_dir)
    said = "Arslan couldn't list the files this push sends"
    assert frame["summary"]["touches"][0] == said and said in frame["reason"]


def test_the_listing_runs_git_through_the_pinned_launcher(repo_dir, monkeypatch):
    fake = _Popen("answers", f"{CI}\0{OTHER}\0".encode())
    monkeypatch.setattr(git_config_guard.subprocess, "Popen", fake)
    assert git_config_guard.outgoing_ci(repo_dir / "src", "git push") == [CI]
    assert [a for a in fake.launched[0][0] if a == "for-each-ref"] == ["for-each-ref"]
    [_, (argv, kw)] = fake.launched
    scratch = Path(kw["env"]["HOME"])
    assert argv[:4] == ["/usr/bin/sandbox-exec", "-p", default_deny_profile(writable=[scratch]), "/usr/bin/git"]
    assert kw["env"] == git_config_guard._env(scratch) and kw["cwd"] == repo_dir
    assert f"--git-dir={repo_dir / '.git'}" in argv and "--no-ext-diff" in argv and "@{upstream}..HEAD" in argv
    assert kw["stdin"] == subprocess.DEVNULL


def _diffs(fake: _Popen) -> list[str]:
    return [a for argv, _ in fake.launched for a in argv if a.endswith("..HEAD")]


def test_with_no_upstream_it_reads_the_named_remotes_head(repo_dir, monkeypatch):
    fake = _Popen("answers", f"{CI}\0".encode(), answers={"for-each-ref": ("answers", b" refs/remotes/o/x\n*\n")})
    monkeypatch.setattr(git_config_guard.subprocess, "Popen", fake)
    assert git_config_guard.outgoing_ci(repo_dir, "git push -u zz-remote topic") == [CI]
    assert _diffs(fake) == ["refs/remotes/zz-remote/HEAD..HEAD"]


def test_a_failed_upstream_read_says_couldnt_list_and_never_falls_back_to_the_remote_head(repo_dir, monkeypatch):
    """With an upstream configured, a failed or timed-out `<upstream>..HEAD` read must not be replaced by the remote
    HEAD's answer (which could show a clean list): it is "couldn't list"."""
    for how in ("fails", "times out"):
        fake = _Popen("answers", answers={"@{upstream}": (how, b""), "/HEAD..HEAD": ("answers", f"{CI}\0".encode())})
        monkeypatch.setattr(git_config_guard.subprocess, "Popen", fake)
        assert git_config_guard.outgoing_ci(repo_dir, "git push") is None
        assert _diffs(fake) == ["@{upstream}..HEAD"]


def test_a_failed_upstream_query_says_couldnt_list(repo_dir, monkeypatch):
    fake = _Popen("answers", f"{CI}\0".encode(), answers={"for-each-ref": ("fails", b"")})
    monkeypatch.setattr(git_config_guard.subprocess, "Popen", fake)
    assert git_config_guard.outgoing_ci(repo_dir, "git push") is None
    assert _diffs(fake) == []


# ── 2. the change list ───────────────────────────────────────────────────────

def test_the_turns_change_list_marks_a_ci_file(monkeypatch):
    finished = {CI: {"saved": "a", "now": "b"}, OTHER: {"saved": None, "now": "c"}}
    monkeypatch.setattr(checkpoints, "manifest", lambda _run: {"created_at": 10.0, "roots": [
        {"path": "/zz", "finished": finished}]})
    paths = checkpoints.changes(1, 0.0)["paths"]
    assert paths == [{"folder": "/zz", "path": CI, "kind": "edited", "ci": True},
                     {"folder": "/zz", "path": OTHER, "kind": "made"}]


# ── 3. the card after a git refusal ──────────────────────────────────────────

def _refused_in(conversation: str, tmp_path: Path, monkeypatch) -> None:
    """A git command in `conversation` whose refusal lines named a held file (faked `git_refused_paths`)."""
    monkeypatch.setattr(command_sandbox, "git_refused_paths",
                        lambda result, **_kw: [str(tmp_path / ".git" / "hooks" / "post-checkout")])
    token = tool_outputs.conversation.set(conversation)
    try:
        terminal_exec.explain({"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"},
                              cwd=tmp_path, closed=[], mode="workspace", timed_out=False, command="git checkout zz")
    finally:
        tool_outputs.conversation.reset(token)


async def test_after_a_git_refusal_the_next_commit_asks_once_and_status_does_not(execution_db, tmp_path,
                                                                               monkeypatch):
    _refused_in("c1", tmp_path, monkeypatch)
    asker = _Asker()
    with permissions.asking_with(asker):
        for command, cid in (("git status", "c1"), ("ls", "c1"), ("git log --oneline", "c1"),
                             ("git commit -m zz", "c2"), ("git add .", "c2")):       # another conversation
            assert await command_gate._git_refused_card(command, cid) is None
        assert asker.frames == []
        assert await command_gate._git_refused_card("git commit -m zz", "c1") is None    # asked, and yes
    [frame] = asker.frames
    assert frame["perm_kind"] == "git_refused" and frame["options"] == ["once"]
    assert "git status" in frame["detail"]
    request = permissions.Request(kind="git_refused", target="git_refused:*", title="t", once_only=True)
    assert hard_rules.never_auto(request) and "git_refused" in hard_rules.NEVER_AUTO_KINDS


@pytest.mark.parametrize("approved", [True, False])
async def test_the_mark_clears_after_the_answer(execution_db, tmp_path, monkeypatch, approved):
    _refused_in("c1", tmp_path, monkeypatch)
    asker = _Asker(approved)
    with permissions.asking_with(asker):
        result = await command_gate._git_refused_card("git add -A", "c1")
        assert (result is None) is approved
        assert await command_gate._git_refused_card("git commit -m zz", "c1") is None
    assert len(asker.frames) == 1


async def test_the_island_cannot_answer_it(execution_db, tmp_path, monkeypatch):
    _refused_in("c1", tmp_path, monkeypatch)
    with permissions.asking_with(approvals.BroadcastAsker("c1")):
        task = asyncio.ensure_future(command_gate._git_refused_card("git commit -am zz", "c1"))
        for _ in range(50):
            await asyncio.sleep(0.01)
            pending = [p for p in approvals.all_pending() if p["frame"].get("perm_kind") == "git_refused"]
            if pending:
                break
        assert pending and pending[0]["island_ok"] is False
        with pytest.raises(approvals.OpenInArslan):
            approvals.answer_by_id(pending[0]["call_id"], True, source="island")
        approvals.answer_by_id(pending[0]["call_id"], True, source="mac")
        assert await task is None


async def test_with_nobody_to_ask_it_is_refused_and_listed(execution_db, tmp_path, monkeypatch):
    _refused_in("c1", tmp_path, monkeypatch)
    refused = await command_gate._git_refused_card("git commit -m zz", "c1")
    assert refused["ok"] is False and "nobody to ask" in refused["error"]
    assert "c1" in command_sandbox.GIT_REFUSED_IN            # nobody answered: still marked
    async with db_session.AsyncSessionLocal() as db:
        listed = await permission_store.refused_groups(db, datetime.utcnow() - timedelta(hours=1))
    assert ("git_refused", 1) in [(row.kind, count) for row, count, _ in listed]


async def test_the_gate_asks_it_before_a_commit_runs(execution_db, tmp_path, monkeypatch):
    async def answer(value):
        return value
    monkeypatch.setattr(command_gate, "_sandbox_enabled", lambda: answer(True))
    monkeypatch.setattr(command_gate, "_asks_for_everything", lambda: answer(False))
    monkeypatch.setattr(command_gate, "_outside_grant", lambda *_a: answer(None))
    monkeypatch.setattr(command_gate, "run_folder", lambda: answer(None))
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(untrusted, "external_seen", lambda: False)
    _refused_in("c1", tmp_path, monkeypatch)
    turn = ToolTurn(resolve_tools=None, emit=lambda _f: None, tool_timeout_s=5, tool_trace=[], convo=[],
                    confirm_command=AsyncMock(return_value=True), conversation_id="c1")
    asker = _Asker(approved=False)
    with permissions.asking_with(asker):
        result = await command_gate.check("run_command", {"command": "git commit -m zz"}, turn)
    assert result["ok"] is False and [f["perm_kind"] for f in asker.frames] == ["git_refused"]
