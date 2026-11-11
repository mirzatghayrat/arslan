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
import json
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
from tests.server.sbx.test_hr1_run_later_link_targets import LAYOUTS as HR1_LAYOUTS
from tests.server.sbx.test_hr1_run_later_link_targets import _lay_out as hr1_lay_out
from tests.server.test_s64_0_outside_content_gaps import memory  # noqa: F401  (the fixture)
from tests.server.test_sub4_report import OUTLINE as _SUB_BRIEF
from tests.server.test_sub4_report import ROOT as _SUB_ROOT
from tests.server.test_sub4_report import _Model as _SubModel
from tests.server.test_sub4_report import _settled as _sub_settled
from tests.server.test_sub4_report import _steps as _sub_steps
from tests.server.test_sub4_report import _wait as _sub_wait
from tests.server.test_sub4_report import runs  # noqa: F401  (the fixture)
from tests.server.test_sub5c_child_folder import _LOG as _SUB_LOG
from tests.server.test_sub5c_child_folder import _SLOW as _SUB_SLOW
from tests.server.test_sub5c_child_folder import _held as _sub_held
from tests.server.test_sub5c_child_folder import _Recorded as _SubRecorded

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
    """On either disk: a Mac's ignores case, so `.VSCode` is the `.vscode` folder; CI's Linux disk doesn't, so it is
    a folder `make_parents` would make, held by the folded name. The Kelvin sign folds to `k` (casefold)."""
    (ws / ".vscode").mkdir()
    (ws / "cfg").symlink_to(ws / ".vscode")
    (ws / "t.json").symlink_to(ws / ".vscode" / "tasks.json")
    for where in (".VSCode/TASKS.json", "cfg/tasks.json", "t.json", ".vscode/tasKs.json"):
        with pytest.raises(RunLater) as held:
            resolve_in_workspace(where, ws, for_write=True, make_parents=True)
        assert held.value.path.name.casefold() == "tasks.json"


def test_the_hooks_path_folder_is_held_by_identity_and_an_unreadable_config_refuses(ws):
    """`TOOLS/Hooks` is the hooks folder on a Mac's disk and a folder `make_parents` would make on CI's (held by the
    folded name, `_within`): held on either."""
    (ws / ".git").mkdir()
    (ws / ".git" / "config").write_text("[core]\n\thooksPath = tools/hooks\n")
    (ws / "tools" / "hooks").mkdir(parents=True)
    (ws / "alias").symlink_to(ws / "tools")
    for where in ("tools/hooks/pre-commit", "TOOLS/Hooks/pre-push", "alias/hooks/pre-commit"):
        with pytest.raises(RunLater):
            resolve_in_workspace(where, ws, for_write=True, make_parents=True)
    assert resolve_in_workspace("tools/build.sh", ws, for_write=True) == ws / "tools" / "build.sh"
    (ws / ".git" / "config").unlink()
    (ws / ".git" / "config").mkdir()                     # can't be read as a file: refused, never taken as unset
    with pytest.raises(PathEscape) as refused:
        resolve_in_workspace("notes.md", ws, for_write=True)
    assert not isinstance(refused.value, RunLater)


def test_not_held_a_dependency_folders_copy_and_a_ci_file(ws):
    for where in ("node_modules/pkg/.vscode/tasks.json", ".github/workflows/ci.yml", "notes.md"):
        assert resolve_in_workspace(where, ws, for_write=True, make_parents=True) == ws / where


def test_a_work_folder_inside_a_dependency_folder_has_no_exemption(tmp_path):
    """As HR-1's `exempts`: a root whose real path passes through node_modules exempts nothing below it."""
    root = tmp_path / "node_modules" / "proj"
    root.mkdir(parents=True)
    root = root.resolve()
    for where in (".vscode/tasks.json", str(root / ".vscode" / "tasks.json")):
        with pytest.raises(RunLater):
            resolve_in_workspace(where, root, for_write=True, make_parents=True)


def test_a_link_named_node_modules_to_an_ordinary_folder_is_no_exemption(ws):
    """The exemption is judged on the real path, as the kernel sees it: a link named node_modules gains nothing."""
    (ws / "plain").mkdir()
    (ws / "node_modules").symlink_to(ws / "plain")
    with pytest.raises(RunLater) as held:
        resolve_in_workspace("node_modules/.vscode/tasks.json", ws, for_write=True, make_parents=True)
    assert held.value.path == ws / "plain" / ".vscode" / "tasks.json"


# ── links at held names (#813 review 9 and 10, as the kernel holds them) ────────

def _folder_link(ws: Path, name: str, target: str) -> None:
    (ws / target).mkdir(parents=True)
    (ws / name).parent.mkdir(parents=True, exist_ok=True)
    (ws / name).symlink_to(ws / target)


def _file_link(ws: Path, name: str, target: str) -> None:
    (ws / target).parent.mkdir(parents=True, exist_ok=True)
    (ws / target).write_text("")
    (ws / name).parent.mkdir(parents=True, exist_ok=True)
    (ws / name).symlink_to(ws / target)


#: The review's probes: a held name or held folder that is a link to an ordinary name. Each was written with no
#: card when only the resolved path was tested. (setup, the path the model gives)
LINK_PROBES = {
    "folder .vscode -> vsc": (lambda ws: _folder_link(ws, ".vscode", "vsc"), ".vscode/tasks.json"),
    "file .envrc -> envrc.real": (lambda ws: _file_link(ws, ".envrc", "envrc.real"), ".envrc"),
    "folder .git -> gd": (lambda ws: _folder_link(ws, ".git", "gd"), ".git/config"),
    "file .vscode/settings.json -> x.json": (lambda ws: _file_link(ws, ".vscode/settings.json", "x.json"),
                                             ".vscode/settings.json"),
    "folder .claude -> c": (lambda ws: _folder_link(ws, ".claude", "c"), ".claude/settings.json"),
    "folder .husky -> h": (lambda ws: _folder_link(ws, ".husky", "h"), ".husky/pre-commit"),
    "file .npmrc -> sib/npmrc": (lambda ws: _file_link(ws, ".npmrc", "sib/npmrc"), ".npmrc"),
    # The resolved path is inside node_modules, which exempted it: the link at a held name takes the exemption away.
    "folder .vscode -> node_modules/x/.vscode": (lambda ws: _folder_link(ws, ".vscode", "node_modules/x/.vscode"),
                                                 ".vscode/tasks.json"),
}


@pytest.mark.parametrize("walk", ["whole", "stopped at once"])
@pytest.mark.parametrize("probe", list(LINK_PROBES))
def test_a_held_name_that_is_a_link_to_an_ordinary_name_is_held(ws, probe, walk, monkeypatch):
    """Held by the path as read at the link, whether or not HR-1's walk of the folder saw the link (`stopped at
    once`: its entry cap reached at the first entry, as in a folder past `WALK_ENTRIES`)."""
    setup, where = LINK_PROBES[probe]
    setup(ws)
    if walk != "whole":
        monkeypatch.setattr(run_later, "WALK_ENTRIES", 0)
    lands = (ws / where).resolve()
    assert run_later.matches(lands, root=ws) is False        # the resolved path alone: nothing would hold it
    with pytest.raises(RunLater) as held:
        resolve_in_workspace(where, ws, for_write=True, make_parents=True)
    assert held.value.path == lands                           # the card names where the write lands
    assert resolve_in_workspace(where, ws, for_write=True, make_parents=True, run_later_ok=lands) == lands
    assert hard_rules.never_auto(permissions.Request(kind="workspace_write", target=str(ws), title="t", detail=where))


def test_a_links_target_is_read_with_the_rest_of_the_path(ws):
    """`p -> .git`, and `.git/hooks` a link to `h2`: neither the path as written (`p/hooks/...`) nor where it lands
    (`h2/...`) has a held name, but `p`'s target with the rest (`.git/hooks/...`) does, as git reads it."""
    (ws / ".git").mkdir()
    (ws / "h2").mkdir()
    (ws / ".git" / "hooks").symlink_to(ws / "h2")
    (ws / "p").symlink_to(ws / ".git")
    with pytest.raises(RunLater) as held:
        resolve_in_workspace("p/hooks/pre-commit", ws, for_write=True)
    assert held.value.path == ws / "h2" / "pre-commit"
    assert hard_rules.never_auto(permissions.Request(kind="workspace_write", target=str(ws), title="t",
                                                     detail="p/hooks/pre-commit"))


def test_a_path_through_a_link_at_a_held_name_has_no_dependency_exemption(ws):
    """`.vscode -> node_modules/x/.husky`: the path read through the link (`.vscode/pre-commit`) is no held name and
    the resolved one is a hook inside node_modules; the kernel's profile drops the exemption then, and so does this."""
    _folder_link(ws, ".vscode", "node_modules/x/.husky")
    with pytest.raises(RunLater) as held:
        resolve_in_workspace(".vscode/pre-commit", ws, for_write=True)
    assert held.value.path == ws / "node_modules" / "x" / ".husky" / "pre-commit"


@pytest.mark.parametrize("layout", sorted(HR1_LAYOUTS))
def test_hr1s_link_target_layouts_hold_what_the_kernel_holds(ws, layout):
    """HR-1's own layouts (`test_hr1_run_later_link_targets.LAYOUTS`, measured under real seatbelt): what the kernel
    refuses at the link's target, named otherwise, is held here; what it writes is written. The held name read through
    the link is held too. The oracle is the kernel's, never a list of this test's own."""
    (link, target, is_folder), writes = HR1_LAYOUTS[layout]
    hr1_lay_out(ws, link, target, is_folder, writes)
    for where, want in writes:
        if want == "refused":
            with pytest.raises(RunLater) as held:
                resolve_in_workspace(where, ws, for_write=True, make_parents=True)
            assert held.value.path == ws / where, where
            through = link + where[len(target):]
            with pytest.raises(RunLater):
                resolve_in_workspace(through, ws, for_write=True, make_parents=True)
        else:
            assert resolve_in_workspace(where, ws, for_write=True, make_parents=True) == ws / where, where


def test_an_alias_anywhere_in_the_folder_takes_the_dependency_exemption_away(ws):
    """#813 review 9: HR-1's walk finds `.vscode -> node_modules/pkg/.vscode`, an alias out of its folder, and the
    kernel's profile then exempts no dependency folder: a hook inside node_modules is held for this write too, though
    the write goes through no link. Without the alias the same write is an ordinary one."""
    (ws / "node_modules" / "other" / ".husky").mkdir(parents=True)
    assert resolve_in_workspace("node_modules/other/.husky/pre-commit", ws, for_write=True) \
        == ws / "node_modules" / "other" / ".husky" / "pre-commit"
    _folder_link(ws, ".vscode", "node_modules/pkg/.vscode")
    with pytest.raises(RunLater):
        resolve_in_workspace("node_modules/other/.husky/pre-commit", ws, for_write=True)
    with pytest.raises(RunLater):                                 # the dependency's file the editor reads
        resolve_in_workspace("node_modules/pkg/.vscode/settings.json", ws, for_write=True)


def test_the_work_folders_hooks_path_inside_a_nested_repository_is_held(ws):
    """⓪Plan's layout: the work folder's config sets `core.hooksPath = tools/githooks`, and `tools` is a submodule
    checkout (its own `.git` file, no hooksPath). The nearest repository above the hook is the submodule, but git in
    the work folder runs the hook: held, as the kernel holds `hooks_path(work folder)`."""
    (ws / ".git" / "modules" / "tools").mkdir(parents=True)
    (ws / ".git" / "config").write_text("[core]\n\thooksPath = tools/githooks\n")
    (ws / ".git" / "modules" / "tools" / "config").write_text("[core]\n\tbare = false\n")
    (ws / "tools" / "githooks").mkdir(parents=True)
    (ws / "tools" / ".git").write_text("gitdir: ../.git/modules/tools\n")
    assert run_later.hooks_path(ws / "tools" / "githooks") is None        # the nearest repository's: none
    with pytest.raises(RunLater):
        resolve_in_workspace("tools/githooks/pre-commit", ws, for_write=True)
    assert resolve_in_workspace("tools/build.sh", ws, for_write=True) == ws / "tools" / "build.sh"


def test_ordinary_links_instruction_files_through_links_and_a_real_dependency_copy_are_not_held(ws):
    _file_link(ws, "notes.md", "n2.md")
    _file_link(ws, "CLAUDE.md", "docs/rules.md")
    _folder_link(ws, ".claude", "c")
    _folder_link(ws, "node_modules/pkg/.vscode", "vsc-of-pkg")    # a package's own link: the kernel's walk skips it
    (ws / "node_modules" / "dep" / ".vscode").mkdir(parents=True)
    for where, lands in (("notes.md", "n2.md"), ("CLAUDE.md", "docs/rules.md"), (".claude/CLAUDE.md", "c/CLAUDE.md"),
                         ("node_modules/dep/.vscode/tasks.json", "node_modules/dep/.vscode/tasks.json"),
                         ("node_modules/pkg/.vscode/tasks.json", "vsc-of-pkg/tasks.json")):
        assert resolve_in_workspace(where, ws, for_write=True, make_parents=True) == ws / lands, where
        assert not hard_rules.never_auto(permissions.Request(kind="workspace_write", target=str(ws), title="t",
                                                             detail=where)), where


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


async def test_a_held_folder_that_is_a_link_asks_its_card_in_arslans_own_folder_and_past_a_grant(db, tmp_path):
    """The review's tool-loop probe: `.claude -> c`. In Arslan's own folder the write asks the run_later card (it
    went through with no card); in a chosen folder the conversation's write grant doesn't answer it."""
    ws = await _own_folder()
    _folder_link(ws, ".claude", "c")
    yes = _Asker(True)
    with permissions.asking_with(yes):
        out = await _dispatch("write_file", {"path": ".claude/settings.json", "content": "{}"})
    assert out["ok"] is True and (ws / "c" / "settings.json").read_text() == "{}"
    assert [(f["perm_kind"], f["target"]) for f in yes.frames] == [("run_later", str(ws / "c" / "settings.json"))]

    chosen = (tmp_path / "chosen").resolve()
    chosen.mkdir()
    _folder_link(chosen, ".claude", "c")
    async with db_session.AsyncSessionLocal() as s:
        await s.merge(Setting(key="workspace_dir", value=str(chosen)))
        await permission_store.add_grant(s, CONV, "", "workspace_write", str(chosen))
        await s.commit()
    ladder = command_confirm.Confirmations(CONV)
    yes = _Asker(True)
    with permissions.asking_with(yes):
        out = await _dispatch("write_file", {"path": ".claude/settings.json", "content": "{}"},
                              confirm_workspace_write=ladder.workspace_write)
    assert out["ok"] is True and [f["perm_kind"] for f in yes.frames] == ["run_later"]
    no = _Asker(False)
    with permissions.asking_with(no):
        out = await _dispatch("write_file", {"path": ".claude/settings.local.json", "content": "{}"},
                              confirm_workspace_write=ladder.workspace_write)
    assert out["ok"] is False and not (chosen / "c" / "settings.local.json").exists()
    assert [f["perm_kind"] for f in no.frames] == ["run_later"]


async def test_an_unreadable_git_config_is_refused_at_the_gate_before_any_card(db, tmp_path):
    """Review item 4: the gate refuses it itself, with the reason, before the folder's card would ask for a write
    the executor refuses anyway."""
    chosen = tmp_path / "chosen"
    (chosen / ".git" / "config").mkdir(parents=True)             # can't be read as a file
    async with db_session.AsyncSessionLocal() as s:
        s.add(Setting(key="workspace_dir", value=str(chosen)))
        await s.commit()
    asked: list[str] = []

    async def folder_card(tool_key, path):
        asked.append(path)
        return True

    async def no_card(frame):
        raise AssertionError(f"no card for a write that can't be judged: {frame}")
    with permissions.asking_with(no_card):
        out = await _dispatch("write_file", {"path": "notes.md", "content": "x"}, confirm_workspace_write=folder_card)
    assert out["ok"] is False and "git config" in out["error"] and asked == []
    assert not (chosen / "notes.md").exists()
    assert hard_rules.never_auto(permissions.Request(kind="workspace_write", target=str(chosen.resolve()),
                                                     title="t", detail="notes.md"))


async def test_the_run_later_card_stands_in_for_the_folders_card(db, tmp_path):
    """One card per write: in a chosen folder with no grant, a held write asks the run_later card and not the
    folder's write card too, whether the click is yes or no."""
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    async with db_session.AsyncSessionLocal() as s:
        s.add(Setting(key="workspace_dir", value=str(chosen)))
        await s.commit()
    folder_cards: list[str] = []

    async def folder_card(tool_key, path):
        folder_cards.append(path)
        return True
    for approved in (True, False):
        asker = _Asker(approved)
        with permissions.asking_with(asker):
            out = await _dispatch("write_file", {"path": ".envrc", "content": str(approved)},
                                  confirm_workspace_write=folder_card)
        assert out["ok"] is approved and [f["perm_kind"] for f in asker.frames] == ["run_later"]
    assert folder_cards == [] and (chosen / ".envrc").read_text() == "True"
    with permissions.asking_with(_Asker(True)):                  # an ordinary write still asks the folder's card
        assert (await _dispatch("write_file", {"path": "notes.md", "content": "x"},
                                confirm_workspace_write=folder_card))["ok"] is True
    assert folder_cards == ["notes.md"]


async def test_a_click_whose_executor_never_ran_approves_nothing_later(db):
    """The gate clears any earlier click first: a click left unused (its step refused after it, say) is not taken by
    the next call's executor, even when that call's own card is declined and the executor runs with no gate."""
    ws = await _own_folder()
    file_tools.approve_run_later(ws / ".envrc")                     # a click whose executor never ran
    with permissions.asking_with(_Asker(False)):
        declined = await _dispatch("write_file", {"path": ".envrc", "content": "declined"})
    assert declined["ok"] is False
    gateless = await file_tools.WriteFileExecutor().execute({"path": ".envrc", "content": "gate-less"})
    assert gateless["ok"] is False and not (ws / ".envrc").exists()


async def test_an_edit_refused_early_leaves_no_click_for_a_later_call(db):
    """⓪Plan's form: an edit with an empty old_string is clicked and returns before it writes; the click is taken
    by that call all the same, so a later executor run with no gate writes nothing."""
    ws = await _own_folder()
    (ws / ".envrc").write_text("old")
    with permissions.asking_with(_Asker(True)):
        out = await _dispatch("edit_file", {"path": ".envrc", "old_string": "", "new_string": "x"})
    assert out["ok"] is False
    gateless = await file_tools.WriteFileExecutor().execute({"path": ".envrc", "content": "gate-less"})
    assert gateless["ok"] is False and (ws / ".envrc").read_text() == "old"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a folder at mode 000")
async def test_a_folder_the_check_cant_read_is_a_tool_error_not_an_exception(db):
    """⓪Plan's form: `locked/sub/x.txt` with `locked` at mode 000 raised PermissionError out of the tool call. Now
    a tool error, with no card and nothing written."""
    ws = await _own_folder()
    (ws / "locked" / "sub").mkdir(parents=True)
    os.chmod(ws / "locked", 0)
    try:
        async def no_card(frame):
            raise AssertionError(f"no card: {frame}")
        with permissions.asking_with(no_card):
            out = await _dispatch("write_file", {"path": "locked/sub/x.txt", "content": "x"})
    finally:
        os.chmod(ws / "locked", 0o755)
    assert out["ok"] is False and "x.txt" in out["error"] and not (ws / "locked" / "sub" / "x.txt").exists()


async def test_two_identical_run_later_asks_at_once_are_two_cards(db):
    """`_NEVER_JOINED`: one click is one write, so an identical ask never joins a card on screen."""
    req = permissions.Request(kind="run_later", target="/ws/.envrc", detail="/ws/.envrc", once_only=True,
                              title="Write .envrc?")
    ctx = permissions.Context(CONV)
    with permissions.asking_with(approvals.BroadcastAsker(CONV)):
        asks = [asyncio.create_task(permissions.decide(req, ctx)) for _ in range(2)]
        for _ in range(200):
            if len([p for p in approvals._pending.values() if not p.future.done()]) == 2:
                break
            await asyncio.sleep(0.01)
        cards = [p.call_id for p in approvals._pending.values() if not p.future.done()]
        for call_id in cards:
            approvals.answer({"type": "confirm_action", "call_id": call_id})
        decisions = await asyncio.wait_for(asyncio.gather(*asks), timeout=5)
    assert len(set(cards)) == 2, f"the second ask joined the first card: {cards}"
    assert [d.allowed for d in decisions] == [True, True]


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
    """Review item 2: the swap lands after the executor's first resolve and before the write, so only the write-time
    re-check (`_write_inside`) sees it: `.vscode`, made by the executor, becomes a link to `.git/hooks`. Without the
    re-check, macOS's O_NOFOLLOW_ANY refuses the open with another error, and Linux would write the hook."""
    ws = await _own_folder()
    (ws / ".git" / "hooks").mkdir(parents=True)
    snapshot = file_tools._snapshot_write
    swapped = []

    def then_swap(root, path, content):
        os.rmdir(ws / ".vscode")
        (ws / ".vscode").symlink_to(ws / ".git" / "hooks")
        swapped.append(path)
        return snapshot(root, path, content)
    monkeypatch.setattr(file_tools, "_snapshot_write", then_swap)
    yes = _Asker(True)
    with permissions.asking_with(yes):
        out = await _dispatch("write_file", {"path": ".vscode/tasks.json", "content": "#!/bin/sh\n"})
    assert swapped == [ws / ".vscode" / "tasks.json"]
    assert yes.frames[0]["target"] == str(ws / ".vscode" / "tasks.json")
    assert out["ok"] is False and "runs later" in out["error"], out
    assert not (ws / ".git" / "hooks" / "tasks.json").exists()


async def test_a_link_swapped_between_the_gate_and_the_executor_fails_closed(db, monkeypatch):
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


# ── a sub-session, in its own folder (SUB5c's write root) ──────────────────────

@pytest.fixture
async def child_ws(runs, tmp_path, monkeypatch):  # noqa: F811
    """SUB5c's harness (real jobs, the real tool loop, gates and cards, a scripted model) in a folder the user chose,
    with the real write_file, recorded. Cleans up as SUB4's `_fresh` does."""
    from server.registry import executors
    from server.services import background_jobs, run_registry, sub_sessions
    monkeypatch.setattr(sub_sessions, "POLL_SECONDS", 0.01)
    for module in (background_jobs, approvals, sub_sessions):
        module._reset_for_tests()
    _SUB_LOG.clear()
    monkeypatch.setitem(executors.EXECUTORS, "write_file", _SubRecorded("write_file", _SUB_LOG))
    folder = tmp_path / "work"
    folder.mkdir()
    async with runs() as db:
        db.add(Setting(key="workspace_dir", value=str(folder)))
        await db.commit()
    sinks: list = []
    yield folder.resolve(), sinks
    monkeypatch.setattr(sub_sessions, "ended", lambda job, text: None)
    for module in (background_jobs, sub_sessions, approvals):
        module._reset_for_tests()
    for cid, sink in sinks:
        run_registry.detach_sink(cid, sink)


async def test_a_sub_sessions_held_write_in_its_own_folder_asks_its_card_and_its_grant_doesnt_answer_it(
        child_ws, monkeypatch):
    """SUB5c x HR-2a: a sub-session writes only in its own folder (`workspace_dir_for_run`), and the hold is judged
    against that write root, as the kernel holds its commands there. Its `.vscode/tasks.json` and
    `.claude/settings.json` each ask a once-only run_later card, past the sub-session's own write grant (and its
    commander's): yes writes the first, no leaves the second unwritten. An ordinary file asks no run_later card.

    The dependency exemption is the write root's: the commander's workspace has an alias at a held name outside the
    sub-session's folder (which takes the exemption away from a walk of the whole workspace), and a copy below the
    sub-session's own node_modules is still written with no card, as its command's profile, walking only its folder,
    would let it."""
    from server.services import run_registry, sub_sessions
    ws, sinks = child_ws
    shown: list = []

    def sink(frame):
        shown.append(frame)
        kind, call_id = frame.get("type"), frame.get("call_id")
        if kind == "propose_workspace_write":
            approvals.answer({"type": "confirm_workspace_write", "call_id": call_id, "scope": "once"})
        elif kind == "propose_action":
            yes = frame.get("perm_kind") == "run_later" and str(frame.get("target", "")).endswith("tasks.json")
            approvals.answer({"type": "confirm_action" if yes else "cancel_action", "call_id": call_id})
    run_registry.attach_sink(_SUB_ROOT, sink)
    sinks.append((_SUB_ROOT, sink))
    model = _SubModel({_SUB_BRIEF: _sub_steps(
        ("write_file", {"path": ".vscode/tasks.json", "content": "{}"}),
        ("write_file", {"path": ".claude/settings.json", "content": "{}"}),
        ("write_file", {"path": "notes.md", "content": "plain"}),
        ("write_file", {"path": "node_modules/pkg/.vscode/tasks.json", "content": "{}"}),
        final="written")}, summary=_sub_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    kid = await _sub_held(model, _SUB_BRIEF)
    folder = ws / "sub" / (await sub_sessions.folder_names(kid))[0]     # made by the server before its first request
    (ws / "elsewhere").mkdir()
    (ws / "plain").mkdir()
    (ws / "elsewhere" / ".vscode").symlink_to(ws / "plain")             # an alias, outside the sub-session's folder
    async with db_session.AsyncSessionLocal() as s:
        for cid in (kid, _SUB_ROOT):
            await permission_store.add_grant(s, cid, "", "workspace_write", str(folder), call_id="card-1")
            await permission_store.add_grant(s, cid, "", "workspace_write", str(ws), call_id="card-2")
        await s.commit()
    model.hold[_SUB_BRIEF].set()
    await _sub_wait(_sub_settled, _SUB_SLOW)

    run_later_cards = [(f["target"], f["options"]) for f in shown
                       if f.get("type") == "propose_action" and f.get("perm_kind") == "run_later"]
    assert run_later_cards == [(str(folder / ".vscode" / "tasks.json"), ["once"]),
                               (str(folder / ".claude" / "settings.json"), ["once"])]
    # The no is the gate's: that write never reached the executor, and the model was told the user said no.
    ran = [(args["path"], result["ok"]) for key, args, result in _SUB_LOG if key == "write_file"]
    assert ran == [(".vscode/tasks.json", True), ("notes.md", True), ("node_modules/pkg/.vscode/tasks.json", True)]
    told = json.dumps(model.requests[_SUB_BRIEF][2], ensure_ascii=False)
    assert "said no" in told and "settings.json" in told
    assert (folder / ".vscode" / "tasks.json").read_text() == "{}"
    assert not (folder / ".claude" / "settings.json").exists()
    assert (folder / "notes.md").read_text() == "plain"                 # the negative control: no run_later card
    assert (folder / "node_modules" / "pkg" / ".vscode" / "tasks.json").read_text() == "{}"
    assert not (ws / ".vscode").exists() and not (ws / ".claude").exists() and not (ws / "notes.md").exists()
