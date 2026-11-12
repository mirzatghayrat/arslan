"""HR-1c (v0.1.64), ⓪Plan's ruling 1: config reached through an include.

D compares git's effective config (`config --list --includes --show-origin`, asked as `view` asks) before and after a
command. A key off the allowlist that appeared or changed through an included file:

- inside the work folder: that file is moved into the quarantine folder and named by key and path, never by value;
- outside it: it is named, and the repository is marked so that its next git command asks first, once, with a card
  the island never answers (with nobody to ask it is refused and listed in the Inbox);
- an allowlisted key (`user.name`) changed through an include is left alone.

Plain stand-ins only; the adversarial shapes are Codex's corpus.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from server.db import session as db_session
from server.orchestrator import command_gate
from server.services import (approvals, command_sandbox, git_config_guard, hard_rules, permission_store, permissions,
                             settings_service, terminal_exec, tool_outputs)
from tests.server.test_hr1c_git_view import STAND_IN, _init, _quarantined, _snap

seatbelt = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                              reason="git is asked in seatbelt, which is macOS-only")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(git_config_guard, "QUARANTINE", tmp_path / "quarantine")
    monkeypatch.setattr(git_config_guard, "UNRESOLVED", {})
    folder = tmp_path / "ws"
    folder.mkdir()
    return Path(os.path.realpath(folder))


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    permissions._reset_for_tests()
    approvals._reset_for_tests()
    monkeypatch.setattr(git_config_guard, "_MARKS", {})
    yield
    permissions._reset_for_tests()
    approvals._reset_for_tests()


@pytest.fixture
def program(tmp_path) -> tuple[Path, Path]:
    """A stand-in program that leaves a marker when anything runs it, and the marker."""
    marker, program = tmp_path / "marker", tmp_path / f"{STAND_IN}.sh"
    program.write_text(f"#!/bin/sh\necho ran >> {marker}\n")
    program.chmod(0o755)
    return program, marker


def _include(git: Path, path: str) -> None:
    with (git / "config").open("a") as config:
        config.write(f"[include]\n\tpath = {path}\n")


def _status(top: Path, home: Path) -> None:
    subprocess.run(["git", "status"], cwd=top, capture_output=True, timeout=60,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"})


class _Asker:
    def __init__(self, approved=True):
        self.frames: list[dict] = []
        self.approved = approved

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": self.approved, "scope": "once" if self.approved else None, "note": "", "by": "mac",
                "call_id": frame["call_id"]}


def _in_folder(monkeypatch, folder: Path) -> None:
    async def workspace_dir(db):
        return folder
    monkeypatch.setattr(settings_service, "workspace_dir", workspace_dir)


# ── inside the work folder: quarantined ──────────────────────────────────────

@pytest.mark.macos
@seatbelt
def test_an_include_in_the_work_folder_given_a_program_key_is_quarantined(ws, tmp_path, program):
    stand_in, marker = program
    git = _init(ws / "r")
    included = ws / "inc.cfg"
    included.write_text("[user]\n\tname = zz\n")
    _include(git, "../../inc.cfg")
    saved = _snap(ws)
    included.write_text(f"[user]\n\tname = zz\n[core]\n\tfsmonitor = {stand_in}\n")
    outcome = git_config_guard.restore(saved)
    assert outcome.includes_moved == ["core.fsmonitor in inc.cfg"] and outcome.marks == {}
    assert not included.exists() and _quarantined(tmp_path) == ["inc.cfg"]
    message = outcome.message()
    assert "core.fsmonitor in inc.cfg" in message and str(stand_in) not in message and STAND_IN not in message
    _status(ws / "r", tmp_path)                                   # git no longer reads it: nothing runs
    assert not marker.exists()


# ── outside it: named, and the next git command asks ────────────────────────

@pytest.mark.macos
@seatbelt
async def test_an_include_outside_the_work_folder_is_named_and_its_next_git_command_asks(
        execution_db, ws, tmp_path, program, monkeypatch):
    stand_in, marker = program
    beside = tmp_path / "beside"
    beside.mkdir()
    outside = beside / "out.cfg"
    outside.write_text("")
    git = _init(ws / "r")
    _include(git, str(outside))
    saved = _snap(ws)
    outside.write_text(f"[core]\n\tfsmonitor = {stand_in}\n")
    token = tool_outputs.conversation.set("c1")
    try:
        message, held = terminal_exec._put_back(saved)           # as terminal_exec._guarded calls it
    finally:
        tool_outputs.conversation.reset(token)
    said = f"core.fsmonitor in {os.path.realpath(outside)}"
    assert said in message and "asks the user first" in message and str(stand_in) not in message and not held
    assert outside.read_text().startswith("[core]")              # outside the work folder: named, not moved
    assert git_config_guard.marked("c1", ws) == {ws / "r": said}
    _in_folder(monkeypatch, ws)
    asker = _Asker()
    with permissions.asking_with(asker):
        assert await command_gate._git_include("ls", "c1") is None and asker.frames == []
        assert await command_gate._git_include("git status", "c1") is None
        frame, = asker.frames
        assert (frame["perm_kind"], frame["options"]) == ("git_include", ["once"])
        assert said in frame["detail"] and str(stand_in) not in frame["detail"]
        assert await command_gate._git_include("git status", "c1") is None and len(asker.frames) == 1
    _status(ws / "r", tmp_path)                                   # the control: the setting is live
    assert marker.exists()


# ── an allowlisted key is left alone ─────────────────────────────────────────

@pytest.mark.macos
@seatbelt
@pytest.mark.parametrize("inside", [True, False])
def test_an_allowlisted_key_changed_through_an_include_is_left_alone(ws, tmp_path, inside):
    included = (ws if inside else tmp_path) / "inc.cfg"
    included.write_text("[user]\n\tname = zz\n")
    git = _init(ws / "r")
    _include(git, str(included))
    saved = _snap(ws)
    included.write_text("[user]\n\tname = yy\n\temail = yy@example.invalid\n")
    outcome = git_config_guard.restore(saved)
    assert outcome.message() == "" and outcome.marks == {} and included.exists()


@pytest.mark.macos
@seatbelt
def test_git_failing_to_list_the_effective_config_refuses_the_next_command_there(ws, monkeypatch):
    """Review delta 1 (G2), flipped: named as unchecked, and the repository's next command is refused until a full
    check succeeds."""
    git = _init(ws / "r")
    saved = _snap(ws)
    assert saved.included == {git: {}}
    monkeypatch.setattr(git_config_guard, "_parse_included", lambda out, direct: None)
    outcome = git_config_guard.restore(saved)
    assert outcome.unanswered == [os.path.join("r", ".git")] and "couldn't ask git" in outcome.message()
    assert outcome.unresolved == {ws / "r": "git couldn't list its settings"}
    git_config_guard.keep_unresolved(outcome.unresolved, saved)
    with pytest.raises(git_config_guard.Refused, match="couldn't list its settings"):
        git_config_guard.resolve("git status", ws / "r")
    assert set(git_config_guard.UNRESOLVED) == {ws / "r", ws / "r" / ".git"}       # its top and its common folder


# ── the card ─────────────────────────────────────────────────────────────────

async def test_the_marked_repositorys_next_git_command_asks_once_and_not_the_island(execution_db, tmp_path,
                                                                                     monkeypatch):
    work, other = tmp_path / "w", tmp_path / "o"
    for folder in (work / "r", other):
        folder.mkdir(parents=True)
    top = Path(os.path.realpath(work / "r"))
    git_config_guard.mark("c1", {top: f"core.fsmonitor in /{STAND_IN}.cfg"})
    request = permissions.Request(kind="git_include", target="x", title="t", once_only=True)
    assert hard_rules.never_auto(request) and "git_include" in hard_rules.NEVER_AUTO_KINDS
    # Not git, another conversation, another working folder: no card.
    _in_folder(monkeypatch, other)
    asker = _Asker()
    with permissions.asking_with(asker):
        assert await command_gate._git_include("git status", "c1") is None
        _in_folder(monkeypatch, work)
        for command, cid in (("ls -la", "c1"), ("cat .gitignore", "c1"), ("git status", "c2")):
            assert await command_gate._git_include(command, cid) is None
        assert asker.frames == []
    # The island can't answer its card; the window's yes runs it once and clears the mark.
    with permissions.asking_with(approvals.BroadcastAsker("c1")):
        task = asyncio.ensure_future(command_gate._git_include("/usr/bin/git log", "c1"))
        for _ in range(50):
            await asyncio.sleep(0.01)
            pending = [p for p in approvals.all_pending() if p["frame"].get("perm_kind") == "git_include"]
            if pending:
                break
        assert pending and pending[0]["island_ok"] is False and pending[0]["frame"]["options"] == ["once"]
        with pytest.raises(approvals.OpenInArslan):
            approvals.answer_by_id(pending[0]["call_id"], True, source="island")
        approvals.answer_by_id(pending[0]["call_id"], True, source="mac")
        assert await task is None
    assert git_config_guard.marked("c1", work) == {}


async def test_a_no_keeps_the_mark_and_with_nobody_to_ask_it_is_refused_and_listed(execution_db, tmp_path,
                                                                                  monkeypatch):
    top = Path(os.path.realpath(tmp_path))
    said = f"core.fsmonitor in /{STAND_IN}.cfg"
    git_config_guard.mark("c1", {top: said})
    _in_folder(monkeypatch, tmp_path)
    with permissions.asking_with(_Asker(approved=False)):
        refused = await command_gate._git_include("git push", "c1")
    assert refused["ok"] is False and git_config_guard.marked("c1", tmp_path) == {top: said}
    refused = await command_gate._git_include("git push", "c1")              # nobody to ask
    assert refused["ok"] is False and "nobody to ask" in refused["error"]
    async with db_session.AsyncSessionLocal() as db:
        listed = await permission_store.refused_groups(db, datetime.utcnow() - timedelta(hours=1))
    assert ("git_include", 1) in [(row.kind, count) for row, count, _ in listed]


@pytest.mark.parametrize(("command", "runs"), [
    ("git status", True), ("/usr/bin/git log", True), ("cd r && git commit -m x", True), ("git-lfs pull", True),
    ("ls", False), ("cat .gitignore", False), ("cd repo.git", False), ("digit", False)])
def test_what_counts_as_a_git_command(command, runs):
    assert git_config_guard.runs_git(command) is runs
