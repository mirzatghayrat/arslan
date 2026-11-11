"""HR-2a: the file tools hold writes into files that make something run later, behind a once-only card.

write_file and edit_file run inside Arslan's own process, so HR-1's kernel hold is not on their path. A write into a
name on HR-1's list (`run_later.matches`, the same matcher, never a second list) or into the repository's
`core.hooksPath` folder is refused by `workspace_paths.resolve_in_workspace(for_write=True)` unless the user clicked
this call's own `run_later` card: in every folder, Arslan's own included, whatever grant exists. The window and the
phone answer it, the island refuses it, and with nobody to ask it is refused and listed in the Inbox. The executor
writes only the path the card named: a link swapped after the click fails closed.

Instruction files (AGENTS.md, CLAUDE.md, CLAUDE.local.md, GEMINI.md, .cursorrules) are ordinary files: no card.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from server.db import session as db_session
from server.db.models import Setting
from server.orchestrator import tool_loop
from server.registry import file_tools
from server.services import (approvals, command_confirm, hard_rules, permission_store, permissions,
                             run_later)
from server.services.workspace_paths import PathEscape, RunLater, resolve_in_workspace

CONV = "conv-hr2a"

#: Written out, not derived: the names the user's ruling names.
NAMED_HELD = (".vscode/tasks.json", ".vscode/launch.json", ".vscode/settings.json", ".mcp.json")
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md", ".cursorrules")


def _example(pattern: str) -> str:
    """A concrete path for one of HR-1's patterns: `*` is a name, a final `**` a hook below the folder."""
    parts = pattern.split("/")
    if parts[-1] == "**":
        parts[-1] = "pre-commit"
    return "/".join(part.replace("*", "x") for part in parts)


#: The rest of #813's list, one example per pattern.
LISTED_HELD = tuple(_example(p) for _, patterns in run_later.FAMILIES for p in patterns)


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return root.resolve()


# ── the write check (workspace_paths) ─────────────────────────────────────────

@pytest.mark.parametrize("name", [*NAMED_HELD, *LISTED_HELD])
def test_each_held_name_is_refused_for_a_write(ws, name):
    for where in (name, f"sub/{name}"):
        with pytest.raises(RunLater) as held:
            resolve_in_workspace(where, ws, for_write=True, make_parents=True)
        assert held.value.path == ws / where
    assert resolve_in_workspace(name, ws, make_parents=True) == ws / name      # reading it is not a write


@pytest.mark.parametrize("name", [*INSTRUCTION_FILES, ".claude/CLAUDE.md", ".codex/AGENTS.md"])
def test_instruction_files_are_ordinary_files(ws, name):
    for where in (name, f"sub/{name}"):
        assert resolve_in_workspace(where, ws, for_write=True, make_parents=True) == ws / where


def test_a_held_name_is_held_in_any_letter_case_and_through_a_link(ws):
    (ws / ".vscode").mkdir()
    (ws / "cfg").symlink_to(ws / ".vscode")
    (ws / "t.json").symlink_to(ws / ".vscode" / "tasks.json")
    for where in (".VSCode/TASKS.json", "cfg/tasks.json", "t.json"):
        with pytest.raises(RunLater) as held:
            resolve_in_workspace(where, ws, for_write=True)
        assert held.value.path.name.lower() == "tasks.json"


def test_the_hooks_path_folder_is_held_by_identity_and_an_unreadable_config_refuses(ws):
    (ws / ".git").mkdir()
    (ws / ".git" / "config").write_text("[core]\n\thooksPath = tools/hooks\n")
    (ws / "tools" / "hooks").mkdir(parents=True)
    (ws / "alias").symlink_to(ws / "tools")
    for where in ("tools/hooks/pre-commit", "TOOLS/Hooks/pre-push", "alias/hooks/pre-commit"):
        with pytest.raises(RunLater):
            resolve_in_workspace(where, ws, for_write=True)
    assert resolve_in_workspace("tools/build.sh", ws, for_write=True) == ws / "tools" / "build.sh"
    (ws / ".git" / "config").unlink()
    (ws / ".git" / "config").mkdir()                     # can't be read as a file: refused, never taken as unset
    with pytest.raises(PathEscape) as refused:
        resolve_in_workspace("notes.md", ws, for_write=True)
    assert not isinstance(refused.value, RunLater)


def test_not_held_a_dependency_folders_copy_and_a_ci_file(ws):
    for where in ("node_modules/pkg/.vscode/tasks.json", ".github/workflows/ci.yml", "notes.md"):
        assert resolve_in_workspace(where, ws, for_write=True, make_parents=True) == ws / where


def test_the_approved_path_passes_and_only_that_one(ws):
    tasks = ws / ".vscode" / "tasks.json"
    ok = resolve_in_workspace(".vscode/tasks.json", ws, for_write=True, make_parents=True, run_later_ok=tasks)
    assert ok == tasks
    with pytest.raises(RunLater):
        resolve_in_workspace(".vscode/launch.json", ws, for_write=True, make_parents=True, run_later_ok=tasks)


# ── never_auto (hard_rules) ──────────────────────────────────────────────────

def test_a_run_later_card_or_a_write_naming_a_held_file_is_never_auto():
    for once in (True, False):
        assert hard_rules.never_auto(permissions.Request(kind="run_later", target="x", title="t", once_only=once))
    assert "run_later" in hard_rules.NEVER_AUTO_KINDS and "run_later" not in hard_rules.MAY_AUTO_KINDS

    def write(detail):
        return permissions.Request(kind="workspace_write", target="/ws", title="t", detail=detail)
    assert hard_rules.never_auto(write(".vscode/tasks.json")) and hard_rules.never_auto(write("a/.git/hooks/x"))
    assert hard_rules.never_auto(write(None))                   # not a path: the user's
    assert not hard_rules.never_auto(write("AGENTS.md")) and not hard_rules.never_auto(write("notes.md"))


# ── the card, through the tool loop and the real executors ─────────────────────

@pytest.fixture
def db(execution_db, monkeypatch, tmp_path):
    permission_store._reset_for_tests()
    approvals._reset_for_tests()
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setattr("server.services.workspace_paths._home", lambda: tmp_path / "home")
    yield execution_db
    approvals._reset_for_tests()


async def _dispatch(key, args, *, confirm_workspace_write=None):
    async def tools():
        return [{"key": key, "description": key}]
    return await tool_loop._dispatch_tool(key, args, "", resolve_tools=tools, emit=lambda e: None,
                                          tool_timeout_s=5, tool_trace=[], convo=[], conversation_id=CONV,
                                          confirm_workspace_write=confirm_workspace_write)


async def _own_folder() -> Path:
    root = await file_tools._workspace_root()
    assert root is not None
    return root.resolve()


class _Asker:
    """A card surface that answers every card with `answer` and keeps the frames."""

    def __init__(self, approved: bool, by: str | None = "mac"):
        self.frames: list[dict] = []
        self.answer = {"approved": approved, "by": by, "scope": "once", "note": ""}

    async def __call__(self, frame):
        self.frames.append(frame)
        return {**self.answer, "call_id": frame["call_id"]}


async def _rows():
    async with db_session.AsyncSessionLocal() as s:
        return list(reversed(await permission_store.recent(s)))


async def test_in_arslans_own_folder_a_held_write_asks_its_own_card_each_time(db):
    ws = await _own_folder()
    yes = _Asker(True)
    with permissions.asking_with(yes):
        first = await _dispatch("write_file", {"path": ".vscode/tasks.json", "content": "one"})
        again = await _dispatch("edit_file", {"path": ".vscode/tasks.json", "old_string": "one", "new_string": "two"})
    assert first["ok"] is True and again["ok"] is True
    assert (ws / ".vscode" / "tasks.json").read_text() == "two"
    assert [f["perm_kind"] for f in yes.frames] == ["run_later", "run_later"]       # no grant: asked each time
    assert all(f["options"] == ["once"] and f["target"] == str(ws / ".vscode" / "tasks.json") for f in yes.frames)
    no = _Asker(False)
    with permissions.asking_with(no):
        refused = await _dispatch("write_file", {"path": ".mcp.json", "content": "{}"})
    assert refused["ok"] is False and "said no" in refused["error"] and not (ws / ".mcp.json").exists()
    rows = await _rows()
    assert [(r.kind, r.decision, r.scope) for r in rows] == [("run_later", "allow", "once")] * 2 + [
        ("run_later", "deny", None)]


async def test_an_instruction_file_is_written_with_no_card(db):
    ws = await _own_folder()

    async def no_card(frame):
        raise AssertionError(f"no card for an instruction file: {frame}")
    with permissions.asking_with(no_card):
        for name in INSTRUCTION_FILES:
            assert (await _dispatch("write_file", {"path": name, "content": "rules"}))["ok"] is True
            assert (ws / name).read_text() == "rules"


async def test_in_a_chosen_folder_a_conversation_grant_does_not_answer_it(db, tmp_path):
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    async with db_session.AsyncSessionLocal() as s:
        s.add(Setting(key="workspace_dir", value=str(chosen)))
        await permission_store.add_grant(s, CONV, "", "workspace_write", str(chosen.resolve()))
        await s.commit()
    ladder = command_confirm.Confirmations(CONV)          # the window's own write callback
    yes = _Asker(True)
    with permissions.asking_with(yes):
        plain = await _dispatch("write_file", {"path": "notes.md", "content": "x"},
                                confirm_workspace_write=ladder.workspace_write)
        held = await _dispatch("write_file", {"path": ".vscode/settings.json", "content": "{}"},
                               confirm_workspace_write=ladder.workspace_write)
    assert plain["ok"] is True and held["ok"] is True
    assert [f["perm_kind"] for f in yes.frames] == ["run_later"]      # the grant answered the plain write only


async def _answered(run, reply):
    """Run `run` with a job's card surface (every window, the Inbox, the island, the phone) and answer its card
    with `reply(call_id)` from outside; returns (result, frame)."""
    seen: list[dict] = []

    async def answer():
        while True:
            for pending in list(approvals._pending.values()):
                if not pending.future.done():
                    seen.append(pending.frame)
                    reply(pending.call_id)
                    return
            await asyncio.sleep(0.01)
    task = asyncio.create_task(answer())
    with permissions.asking_with(approvals.BroadcastAsker(CONV)):
        result = await run
    task.cancel()                                          # no card opened: nothing to answer
    await asyncio.gather(task, return_exceptions=True)
    assert seen, f"no card was shown: {result}"
    return result, seen[0]


async def test_the_window_and_the_phone_answer_it(db):
    ws = await _own_folder()
    for name, source in ((".envrc", None), (".npmrc", "phone")):
        reply = {"type": "confirm_action"} | ({"source": source} if source else {})
        result, frame = await _answered(_dispatch("write_file", {"path": name, "content": "x"}),
                                        lambda call_id, reply=reply: approvals.answer(reply | {"call_id": call_id}))
        assert result["ok"] is True and (ws / name).read_text() == "x"
        assert frame["perm_kind"] == "run_later" and not approvals.window_only(frame)
    assert [(r.kind, r.decision, r.scope) for r in await _rows()] == [("run_later", "allow", "once")] * 2


async def test_the_island_refuses_it(db):
    ws = await _own_folder()
    island = []

    def reply(call_id):
        try:
            approvals.answer_by_id(call_id, True, source="island")
        except approvals.OpenInArslan:
            island.append("open in Arslan")
        approvals.answer({"type": "cancel_action", "call_id": call_id})        # then the window says no
    result, frame = await _answered(_dispatch("write_file", {"path": ".gitmodules", "content": "x"}), reply)
    assert island == ["open in Arslan"] and approvals.island_may_answer(frame) is False
    assert result["ok"] is False and not (ws / ".gitmodules").exists()


async def test_with_nobody_to_ask_it_is_refused_and_listed_in_the_inbox(db):
    ws = await _own_folder()
    out = await _dispatch("write_file", {"path": ".vscode/launch.json", "content": "{}"})
    [row] = await _rows()
    assert out["ok"] is False and "nobody to ask" in out["error"] and not (ws / ".vscode" / "launch.json").exists()
    assert (row.kind, row.decided_by, row.decision) == ("run_later", "policy", "deny")
    assert permission_store.could_not_ask(row) and not (row.extra or {}).get(permissions.ALWAYS_KEY)


async def test_a_link_swapped_after_the_click_fails_closed(db, monkeypatch):
    ws = await _own_folder()
    (ws / ".vscode").mkdir()
    (ws / ".git" / "hooks").mkdir(parents=True)
    (ws / "d").symlink_to(ws / ".vscode")
    approve = file_tools.approve_run_later

    def then_swap(path):
        approve(path)
        if path is not None:                                 # the click: between it and the write
            os.unlink(ws / "d")
            (ws / "d").symlink_to(ws / ".git" / "hooks")
    monkeypatch.setattr(file_tools, "approve_run_later", then_swap)
    yes = _Asker(True)
    with permissions.asking_with(yes):
        out = await _dispatch("write_file", {"path": "d/tasks.json", "content": "#!/bin/sh\n"})
    assert yes.frames[0]["target"] == str(ws / ".vscode" / "tasks.json")
    assert out["ok"] is False and "runs later" in out["error"]
    assert not (ws / ".git" / "hooks" / "tasks.json").exists() and not (ws / ".vscode" / "tasks.json").exists()


async def test_a_click_approves_one_call_only(db):
    """The token is taken by the call it was given for: an executor run again without the gate writes nothing."""
    ws = await _own_folder()
    with permissions.asking_with(_Asker(True)):
        assert (await _dispatch("write_file", {"path": ".envrc", "content": "one"}))["ok"] is True
    again = await file_tools.WriteFileExecutor().execute({"path": ".envrc", "content": "two"})
    assert again["ok"] is False and (ws / ".envrc").read_text() == "one"
