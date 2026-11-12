"""SBX-10 (v0.1.64): a sub-session's run-later walk covers its commander's whole workspace, not just its own folder.

⑤CAP, probing #851: a sub-session writes only in `<workspace>/sub/<name>/`, and HR-1's walk looked only there. A link
at a held name in the commander's workspace, outside that folder, whose real path is inside it (`.git/hooks ->
sub/kid/hk`, `.vscode -> sub/kid/v`), or the commander's `core.hooksPath` set into it, let the sub-session write what
is, from the commander's side, a file that makes something run later. Now its profile walks the commander's workspace
(`walk_root`, pinned with the folder) and holds those targets; writes stay in its own folder.

- Real seatbelt, through `terminal_exec.run`: the three layouts refused with the commander's workspace as the walk
  root, the files unchanged; the same layout with the child folder as its own workspace (no commander) as before.
- Fail closed: a walk root that is a link, or doesn't hold the folder, refuses with the note (seatbelt); the executor
  refuses a sub-session's command when the commander's workspace isn't known or doesn't hold its folder (any OS).

Stand-in names and plain paths only.
"""
import sys

import pytest

from server.registry.executors import EXECUTORS
from server.services import checkpoints, command_sandbox, run_later, sandbox_profile, settings_service, terminal_exec
from tests.server.sbx.test_sbx9_root_pin import home  # noqa: F401  (the fixture: scratch HOME, temp and data)

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")
STAND_IN = "zz-stand-in-word"

#: (what the commander's workspace holds, the files the child writes, by its own folder: (path, want)).
LAYOUTS = {
    "git-hooks": ([(".git/hooks", "hk")], [("hk/pre-commit", "refused"), (f"{STAND_IN}.txt", "done")]),
    "vscode": ([(".vscode", "v")], [("v/settings.json", "refused"), ("v/other.json", "done")]),
    "hooks-path": ([], [("hp/pre-commit", "refused"), (f"{STAND_IN}.txt", "done")]),
}


def _lay_out(tmp_path, layout):
    """The commander's workspace `ws`, the child's folder `ws/sub/kid` with its files ("old"), and the commander's
    links into it; for hooks-path the commander's config sets `core.hooksPath` there and the child has a `.git` of
    its own (so the child's nearest repository is its own). Under the scratch HOME (`home`)."""
    ws = (tmp_path / "home" / "ws").resolve()
    kid = ws / "sub" / "kid"
    links, writes = LAYOUTS[layout]
    for path, _ in writes:
        (kid / path).parent.mkdir(parents=True, exist_ok=True)
        (kid / path).write_text("old")
    (ws / ".git").mkdir(parents=True, exist_ok=True)
    for name, target in links:
        (ws / name).symlink_to(kid / target, target_is_directory=True)
    if layout == "hooks-path":
        (ws / ".git" / "config").write_text("[core]\n\thooksPath = sub/kid/hp\n")
        (kid / ".git").mkdir()
    return ws, kid, writes


def _writes(writes) -> str:
    return "; ".join(f"(printf zz > '{p}') 2>/dev/null && echo done || echo refused" for p, _ in writes)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("layout", sorted(LAYOUTS))
@pytest.mark.parametrize("commander", [True, False], ids=["sub-session", "own-workspace"])
@pytest.mark.usefixtures("home")
async def test_a_commanders_link_into_the_childs_folder_is_held_in_the_childs_profile(tmp_path, layout, commander):
    """With the commander's workspace as the walk root the held targets are refused and stay "old"; the child's
    other files are written. The control: the child folder as its own workspace, no commander, writes them all."""
    ws, kid, writes = _lay_out(tmp_path, layout)
    result = await terminal_exec.run(_writes(writes), cwd=kid, sandbox=True, offline=True,
                                     walk_root=ws if commander else None)
    assert result["sandbox"] == "workspace", result
    want = [w for _, w in writes] if commander else ["done"] * len(writes)
    assert result["stdout"].split() == want, result
    for (path, _), got in zip(writes, want):
        assert (kid / path).read_text() == ("old" if got == "refused" else "zz"), path


@pytest.mark.macos
@macos
@pytest.mark.parametrize("which", ["link", "elsewhere"])
@pytest.mark.usefixtures("home")
async def test_a_walk_root_that_cant_be_pinned_or_doesnt_hold_the_folder_refuses_with_the_note(tmp_path, which):
    ws, kid, writes = _lay_out(tmp_path, "vscode")
    other, alias = ws.parent / "other", ws.parent / "ws-link"
    other.mkdir()
    alias.symlink_to(ws, target_is_directory=True)
    walk = alias if which == "link" else other
    result = await terminal_exec.run(_writes(writes), cwd=kid, sandbox=True, offline=True, walk_root=walk)
    assert result["code"] == "root_swapped" and result["exit_code"] is None, result
    assert "Nothing ran" in result["note"]
    assert [(kid / p).read_text() for p, _ in writes] == ["old", "old"]
    assert command_sandbox._PINS == {}


@pytest.mark.parametrize("hooks_path", [False, True], ids=["no-hooks-path", "hooks-path"])
def test_the_git_config_lift_stays_in_the_sub_sessions_folder(tmp_path, hooks_path):
    """HR-1b with SBX-10 (any OS, the profile's filters): the walk root adds its hooksPath target and lifts nothing,
    so under the git_config grant a config name is lifted only in the child's folder, where git_config_guard looks."""
    ws = (tmp_path / "ws").resolve()
    kid = ws / "sub" / "kid"
    (kid / "hp").mkdir(parents=True)
    (ws / ".git").mkdir()
    if hooks_path:
        (ws / ".git" / "config").write_text("[core]\n\thooksPath = sub/kid/hp\n")
    alone = run_later.kernel_filters([kid], git_config_ok=True)
    walked = run_later.kernel_filters([kid], git_config_ok=True, walk_roots=[ws])
    families = len(run_later.FAMILIES)
    assert walked[:families] == alone[:families]          # the same names, the same lift: only in `kid`
    assert walked[families:] == ([(sandbox_profile.subpath(kid / "hp"),)] if hooks_path else [])


def _deep_layout(tmp_path):
    """Review delta 1 (b): the child's folder `ws/sub/kid` holds `x/.vscode -> v`, three folders below the commander's
    workspace and one below the child's folder; the walk's depth cap is set to 2 by the tests."""
    ws = (tmp_path / "home" / "ws").resolve()
    kid = ws / "sub" / "kid"
    (kid / "x" / "v").mkdir(parents=True)
    (kid / "x" / "v" / "settings.json").write_text("old")
    (kid / f"{STAND_IN}.txt").write_text("old")
    (kid / "x" / ".vscode").symlink_to(kid / "x" / "v", target_is_directory=True)
    return ws, kid


def test_the_childs_own_folder_is_walked_with_its_own_depth_budget(tmp_path, monkeypatch):
    """Review delta 1 (b), any OS: past the depth cap counted from the commander's workspace, but within it from the
    child's folder, the child's link target is still found (the child's folder is walked from its own root, first)."""
    monkeypatch.setattr(run_later, "WALK_DEPTH", 2)
    ws, kid = _deep_layout(tmp_path)
    hold = command_sandbox.run_later_folders([kid], walk_roots=[ws])
    assert kid / "x" / "v" in hold.kept and hold.complete
    assert sandbox_profile.literal(kid / "x" / "v" / "settings.json") in hold.at_targets


@pytest.mark.macos
@macos
@pytest.mark.usefixtures("home")
async def test_a_link_deep_in_the_childs_folder_is_held_past_the_commanders_depth_cap(tmp_path, monkeypatch):
    """Review delta 1 (b), real seatbelt: the child's write to the link's target is refused, the file stays "old";
    its other file is written."""
    monkeypatch.setattr(run_later, "WALK_DEPTH", 2)
    ws, kid = _deep_layout(tmp_path)
    writes = [("x/v/settings.json", "refused"), (f"{STAND_IN}.txt", "done")]
    result = await terminal_exec.run(_writes(writes), cwd=kid, sandbox=True, offline=True, walk_root=ws)
    assert result["sandbox"] == "workspace", result
    assert result["stdout"].split() == ["refused", "done"], result
    assert [(kid / p).read_text() for p, _ in writes] == ["old", "zz"]


def _shared_layout(tmp_path):
    """Review delta 1 (c): `ws/.vscode -> shared` and `ws/sub/.claude -> ../shared`, two families' aliases of one
    folder (the walk lists `ws` before `ws/sub`, so `.vscode`'s is met first). In `shared`: `settings.json` (both
    families hold it), `tasks.json -> ../t.json` (the editor family's name) and `settings.local.json -> ../c.json`
    (the agent family's, by its `settings*.json` pattern, so only listing `shared` as `.claude` maps it)."""
    ws = (tmp_path / "home" / "ws").resolve()
    shared = ws / "shared"
    (ws / "sub").mkdir(parents=True)
    shared.mkdir()
    for path in ("shared/settings.json", "t.json", "c.json", f"{STAND_IN}.txt"):
        (ws / path).write_text("old")
    (shared / "tasks.json").symlink_to(ws / "t.json")
    (shared / "settings.local.json").symlink_to(ws / "c.json")
    (ws / ".vscode").symlink_to(shared, target_is_directory=True)
    (ws / "sub" / ".claude").symlink_to(shared, target_is_directory=True)
    return ws


def test_each_alias_of_a_shared_folder_maps_its_own_names(tmp_path):
    """Review delta 1 (c), any OS: both aliases' names are held at the shared folder, the links in it included."""
    ws = _shared_layout(tmp_path)
    filters = run_later.held_folders([ws]).link_filters
    for path in ("shared/settings.json", "t.json", "c.json"):
        assert sandbox_profile.literal(ws / path) in filters, path


@pytest.mark.macos
@macos
@pytest.mark.usefixtures("home")
async def test_two_families_aliases_of_one_folder_are_both_held(tmp_path):
    """Review delta 1 (c), real seatbelt: the editor family's name and the agent family's name, each through the link
    in the shared folder, and the name both hold, are refused and stay "old"; an ordinary file is written."""
    ws = _shared_layout(tmp_path)
    writes = [("shared/settings.json", "refused"), ("t.json", "refused"), ("c.json", "refused"),
              (f"{STAND_IN}.txt", "done")]
    labelled = "; ".join(f"(printf zz > '{p}') 2>/dev/null && echo {p}=done || echo {p}=refused" for p, _ in writes)
    result = await terminal_exec.run(labelled, cwd=ws, sandbox=True, offline=True)   # distinct lines (no folding)
    assert result["sandbox"] == "workspace", result
    assert result["stdout"].split() == [f"{p}={w}" for p, w in writes], result
    assert [(ws / p).read_text() for p, _ in writes] == ["old", "old", "old", "zz"]


@pytest.fixture
def sub_session(execution_db, tmp_path, monkeypatch):
    """A sub-session's run (its folder `ws/sub/kid`), the sandbox available, `terminal_exec.run` recorded."""
    ws = (tmp_path / "ws").resolve()
    kid = ws / "sub" / "kid"
    kid.mkdir(parents=True)
    ran: list[dict] = []
    state = {"workspace": ws}

    async def run(command, **kw):
        ran.append(kw)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(kw["cwd"])}

    async def for_run(db):
        return kid

    async def workspace(db):
        return state["workspace"]

    async def no_save(*args, **kwargs):
        return None
    monkeypatch.setattr(settings_service, "run_sub_folder", lambda: ("kid",))
    monkeypatch.setattr(settings_service, "workspace_dir_for_run", for_run)
    monkeypatch.setattr(settings_service, "workspace_dir", workspace)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(checkpoints, "ensure", no_save)
    monkeypatch.setattr(terminal_exec, "run", run)
    return ws, kid, state, ran


async def test_a_sub_sessions_command_walks_its_commanders_workspace(sub_session):
    ws, kid, _, ran = sub_session
    result = await EXECUTORS["run_command"].execute({"command": "true"})
    assert result["ok"], result
    [kw] = ran
    assert (kw["cwd"], kw["walk_root"], kw["sandbox"]) == (kid, ws, True)


@pytest.mark.parametrize("commander", ["unknown", "elsewhere"])
async def test_an_unknown_commander_workspace_refuses_the_command(sub_session, tmp_path, commander):
    _, _, state, ran = sub_session
    state["workspace"] = None if commander == "unknown" else (tmp_path / "other").resolve()
    result = await EXECUTORS["run_command"].execute({"command": "true"})
    assert result["ok"] is False and result["executed"] is False, result
    assert "commander's workspace" in result["error"] and "nothing ran" in result["error"]
    assert ran == []
