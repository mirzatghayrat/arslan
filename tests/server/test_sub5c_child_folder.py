"""SUB5c (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md, SUB5 point 7): each sub-session writes only in its own
folder, `<workspace>/sub/<short name>/` (a grandchild's inside its parent's), made by the server. Reads keep the whole
workspace; the commander still writes anywhere.

SUB4's harness: real jobs through the background job runner, the real `background_body`, tool loop, gates and cards,
with a scripted model. The file tools and `run_command`'s gate and executor are the real ones; the command itself runs
under the real seatbelt on a Mac (`available()` pins it off on Linux CI), and is recorded at `terminal_exec.run`
elsewhere.
"""
import asyncio
import json
import os
import sys

import pytest

from server.db.models import Setting
from server.orchestrator import arslan as arslan_mod, command_gate
from server.registry import executors
from server.services import command_sandbox, settings_service, sub_sessions, terminal_exec, workspace_paths
from tests.server.test_s2a1_sandbox import PLAIN_OSA
from tests.server.test_s2a3_wire import STAND_IN, unread  # noqa: F401  (the fixture)
from tests.server.test_s64_0_outside_content_gaps import memory  # noqa: F401  (the fixture)
from tests.server.test_sub4_report import (  # noqa: F401  (the fixture)
    OUTLINE, ROOT, _children, _Model, _settled, _sink, _start, _steps, _wait, runs)

#: The real tools, taken before any fixture stubs one.
_REAL = {key: executors.EXECUTORS[key] for key in ("write_file", "edit_file", "read_file", "run_command")}
_SEATBELT = command_sandbox.available
_MAC_ONLY = pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS's")
_LOG: list = []


class _Recorded:
    """The real executor, its results kept in `log` as (tool, args, result)."""

    def __init__(self, key, log):
        self.key, self.real, self.log = key, _REAL[key], log

    def __getattr__(self, name):
        return getattr(self.real, name)

    async def execute(self, args):
        result = await self.real.execute(args)
        self.log.append((self.key, args, result))
        return result


@pytest.fixture
async def ws(runs, tmp_path, monkeypatch):  # noqa: F811
    """A working folder the user chose (so each write asks its card), and the real tools, recorded."""
    _LOG.clear()
    for key in _REAL:
        monkeypatch.setitem(executors.EXECUTORS, key, _Recorded(key, _LOG))
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "shared.md").write_text("the commander's text")
    async with runs() as db:
        db.add(Setting(key="workspace_dir", value=str(folder)))
        await db.commit()
    return folder.resolve()


def _results(tool):
    return [result for key, _, result in _LOG if key == tool]


async def _folder(ws, kid):
    return ws / "sub" / (await sub_sessions.folder_names(kid))[0]


async def _held(model, brief=OUTLINE):
    """Start a sub-session whose first model request waits; its id once that request is in."""
    model.hold[brief] = asyncio.Event()
    await _start(brief)
    await _wait(lambda: model.requests[brief])
    [job] = _children()
    return job.conversation_id


async def test_a_childs_file_tools_write_only_in_its_own_folder_and_its_card_names_it(ws, monkeypatch):
    shown = _sink(ROOT)
    model = _Model({OUTLINE: _steps(
        ("write_file", {"path": "outline.md", "content": "# Outline"}),
        ("write_file", {"path": "../../escape.md", "content": "x"}),
        ("write_file", {"path": str(ws / "escape2.md"), "content": "x"}),
        ("edit_file", {"path": "../../shared.md", "old_string": "commander's", "new_string": "child's"}),
        ("edit_file", {"path": str(ws / "shared.md"), "old_string": "commander's", "new_string": "child's"}),
        ("edit_file", {"path": "outline.md", "old_string": "# Outline", "new_string": "# Outline v2"}),
        ("read_file", {"path": "../../shared.md"}),
        final="outline ready")}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE)
    await _wait(_settled)
    [job] = _children()
    folder = await _folder(ws, job.conversation_id)
    assert (folder / "outline.md").read_text() == "# Outline v2"
    assert sorted(os.listdir(ws)) == ["shared.md", "sub"]
    assert (ws / "shared.md").read_text() == "the commander's text"
    writes, edits = _results("write_file"), _results("edit_file")
    assert [r["ok"] for r in writes] == [True, False, False] and [r["ok"] for r in edits] == [False, False, True]
    for refused in (*writes[1:], *edits[:2]):
        assert "outside the workspace" in refused["error"] and str(folder) in refused["note"]
    # Reads keep the whole workspace, from its own folder.
    [read] = _results("read_file")
    assert read["ok"] is True and read["content"] == "the commander's text"
    # Its write card, shown in the commander's window, names its own folder.
    cards = [f for f in shown if f.get("type") == "propose_workspace_write"]
    assert cards and {card["workspace"] for card in cards} == {str(folder)}
    assert all(card["sub_session"] is True for card in cards)


async def test_the_commander_still_writes_anywhere_also_in_a_childs_folder(ws, monkeypatch):
    _sink(ROOT)

    async def tools():
        return [{"key": key, "description": "fixture"} for key in ("write_file", "update_plan")]
    monkeypatch.setattr(arslan_mod, "_background_tools", tools)
    monkeypatch.setattr(arslan_mod, "_background_callable", tools)
    model = _Model({OUTLINE: _steps(("write_file", {"path": "outline.md", "content": "# Outline"}))},
                   summary=_steps(("write_file", {"path": "top.md", "content": "merged"}),
                                  ("write_file", {"path": "sub/elsewhere/notes.md", "content": "n"}),
                                  final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE)
    await _wait(_settled)
    [job] = _children()
    folder = await _folder(ws, job.conversation_id)
    assert (folder / "outline.md").read_text() == "# Outline"
    # The summary turn is the commander's job, in the workspace: written where it said.
    assert (ws / "top.md").read_text() == "merged" and (ws / "sub" / "elsewhere" / "notes.md").read_text() == "n"
    assert [r["path"] for r in _results("write_file")] == ["outline.md", "top.md", "sub/elsewhere/notes.md"]


async def _grant_outside(*cids):
    from server.db import session as db_session
    from server.services import permission_store
    async with db_session.AsyncSessionLocal() as db:
        for cid in cids:
            await permission_store.add_grant(db, cid, "", "outside", "*", call_id="card-1")
        await db.commit()


@pytest.mark.parametrize("lever", ["outside grant", "sandbox switched off"])
async def test_a_childs_outside_grant_or_the_sandbox_switch_doesnt_let_its_commands_out(ws, monkeypatch, lever):
    """Recorded at `terminal_exec.run`, so on any OS. The same lever on the commander and on its sub-session: the
    commander's command (its summary turn) runs outside the sandbox, so the lever works; the sub-session's still runs
    in the sandbox, in its own folder, never bare, and asked to leave it, it doesn't run."""
    _sink(ROOT)
    ran = []

    async def run(command, **kw):
        ran.append(kw)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(kw["cwd"]), "sandbox": "workspace"}
    monkeypatch.setattr(terminal_exec, "run", run)
    if lever == "sandbox switched off":
        async def off(*_):
            return False
        monkeypatch.setattr(command_gate, "_sandbox_enabled", off)
        monkeypatch.setattr(settings_service, "terminal_sandbox_enabled", off)
    outside = {"command": "ls", "outside_sandbox": True, "why": "it needs the whole disk"}
    model = _Model({OUTLINE: _steps(("run_command", {"command": "ls"}), ("run_command", outside))},
                   summary=_steps(("run_command", {"command": "ls"}), final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    kid = await _held(model)
    if lever == "outside grant":
        await _grant_outside(kid, ROOT)
    model.hold[OUTLINE].set()
    await _wait(_settled)
    folder = await _folder(ws, kid)
    child, commander = ran
    assert (child["cwd"], child["sandbox"], child["unwrapped"]) == (folder, True, False)
    assert (commander["cwd"], commander["sandbox"]) == (ws, False)
    # The second command never reached the executor: the gate refused it, and said why.
    assert [r["ok"] for r in _results("run_command")] == [True, True]
    assert "can't run outside it" in json.dumps(model.requests[OUTLINE][-1], ensure_ascii=False)


@_MAC_ONLY
async def test_under_the_real_seatbelt_a_childs_command_writes_only_in_its_folder_even_with_a_grant(ws, monkeypatch):
    if not _SEATBELT():
        pytest.skip("seatbelt can't start here (it can't nest inside another sandbox)")
    monkeypatch.setattr(command_sandbox, "available", _SEATBELT)
    _sink(ROOT)
    command = "echo in > inside.txt; echo out > ../../escape.txt; echo out > ../elsewhere.txt; cat ../../shared.md"
    model = _Model({OUTLINE: _steps(("run_command", {"command": command}))}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    kid = await _held(model)
    await _grant_outside(kid)
    model.hold[OUTLINE].set()
    await _wait(_settled)
    folder = await _folder(ws, kid)
    [result] = _results("run_command")
    assert result["sandbox"] == "workspace" and result["cwd"] == str(folder)
    assert (folder / "inside.txt").read_text() == "in\n"
    assert not (ws / "escape.txt").exists() and not (folder.parent / "elsewhere.txt").exists()
    assert "Operation not permitted" in result["stderr"]
    assert "the commander's text" in result["stdout"]          # reads keep the whole workspace


async def test_a_childs_folder_swapped_for_a_link_out_is_refused_and_nothing_lands_outside(ws, tmp_path, monkeypatch):
    _sink(ROOT)

    async def own_folder(db):
        return True                                 # no write card: the write reaches the file tool
    monkeypatch.setattr(settings_service, "workspace_is_default", own_folder)
    out = tmp_path / "outside"
    out.mkdir()
    model = _Model({OUTLINE: _steps(("write_file", {"path": "planted.md", "content": "x"}),
                                    ("run_command", {"command": "echo x > planted.txt"}))},
                   summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    kid = await _held(model)
    folder = await _folder(ws, kid)                 # made by the server before its first request
    os.rmdir(folder)
    os.symlink(out, folder)
    model.hold[OUTLINE].set()
    await _wait(_settled)
    assert os.listdir(out) == []
    # With no folder to write in, the step's tools no longer offer write_file (`tool.read_offer`), and the command is
    # refused by its executor.
    assert _results("write_file") == [] and "tool 'write_file' is not available" in json.dumps(
        model.requests[OUTLINE][1], ensure_ascii=False)
    [command] = _results("run_command")
    assert command["ok"] is False and "that folder can't be used" in command["error"]


# -- each layer on its own: the gate, the executor, the fallback --------------------------------------------------

def _ctx(names):
    from server.services import personal_context as pc
    return pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="sub-kid", sub_folder=names)


async def _no_card(frame):
    raise AssertionError("no card is shown")


def _turn(confirm_command=None):
    from server.orchestrator.turn_state import ToolTurn
    return ToolTurn(resolve_tools=None, emit=lambda e: None, tool_timeout_s=20.0, tool_trace=[], convo=[],
                    conversation_id="sub-kid", confirm_command=confirm_command)


@pytest.mark.parametrize("names, commander", [((), True), (("kid",), False)], ids=["commander", "sub-session"])
async def test_the_gate_never_lets_a_sub_sessions_command_out_under_its_grant(ws, unread, names, commander):  # noqa: F811
    """Under the same grant: the commander's command runs outside, and an unread one asks (here nobody can be asked,
    so it is refused). The sub-session's runs in the sandbox, and an unread one runs offline there with no card, as for
    a conversation with no grant. Asked to leave the sandbox, it is refused."""
    from server.services import permissions, personal_context as pc, terminal_policy
    await _grant_outside("sub-kid")
    with pc.bind(_ctx(names)), permissions.asking_with(_no_card):
        plan = await command_gate.check("run_command", {"command": "ls"}, _turn())
        unread_plan = await command_gate.check("run_command", {"command": STAND_IN}, _turn())
        refused = await command_gate.check("run_command", {"command": "ls", "outside_sandbox": True, "why": "x"},
                                           _turn())
    assert (plan.run_outside, plan.by_grant, plan.sandbox_on) == (commander, commander, True)
    if commander:
        assert isinstance(unread_plan, dict) and not isinstance(refused, dict)
    else:
        assert unread_plan.offline_reason == terminal_policy.UNREADABLE and unread_plan.run_outside is False
        assert isinstance(refused, dict) and "can't run outside it" in refused["error"]


@pytest.mark.parametrize("names, commander", [((), True), (("kid",), False)], ids=["commander", "sub-session"])
async def test_the_gate_keeps_a_sub_sessions_command_in_the_sandbox_when_it_is_switched_off_or_approved_bare(
        ws, monkeypatch, names, commander):
    """The switch off: the commander's plain command needs a card (nobody to ask here: refused), the sub-session's
    runs in the sandbox with none. An Apple Events call the user's click approved: the commander's runs bare, the
    sub-session's stays wrapped in its sandbox."""
    from server.services import permissions, personal_context as pc

    async def clicked(command, argv, **kw):
        permissions.LAST_DECISION.set(permissions.Decision(True, "user", "once"))
        return True
    with pc.bind(_ctx(names)), permissions.asking_with(_no_card):
        bare = await command_gate.check("run_command", {"command": PLAIN_OSA}, _turn(clicked))

        async def off():
            return False
        monkeypatch.setattr(command_gate, "_sandbox_enabled", off)
        switched_off = await command_gate.check("run_command", {"command": "ls"}, _turn())
    assert (bare.unwrapped, bare.run_outside, bare.kept_wrapped) == (commander, commander, not commander)
    assert isinstance(switched_off, dict) is commander
    if not commander:
        assert (switched_off.sandbox_on, switched_off.run_outside) == (True, False)


@pytest.mark.parametrize("names", [(), ("kid",)], ids=["commander", "sub-session"])
async def test_the_executor_keeps_a_sub_sessions_command_in_its_folders_sandbox_whatever_the_loop_set(
        ws, monkeypatch, names):
    """The loop let it out, bare, with its delete going to the Trash, and Desktop, Documents and Downloads closed: the
    commander's delete goes to the Trash; the sub-session's command runs in the sandbox, in its folder, with the
    workspace still readable, and with no sandbox that can start it doesn't run. (The commander's sandbox flags under
    the same loop: the end-to-end test above.)"""
    from server.services import delete_to_trash, permissions, personal_context as pc
    ran, trashed = [], []

    async def run(command, **kw):
        ran.append(kw)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(kw["cwd"])}

    async def closed(db):
        return False
    monkeypatch.setattr(terminal_exec, "run", run)
    monkeypatch.setattr(delete_to_trash, "move", lambda command, cwd: trashed.append(cwd) or {"ok": True})
    monkeypatch.setattr(settings_service, "default_read_enabled", closed)
    tokens = (terminal_exec.OUTSIDE_SANDBOX.set(True), terminal_exec.UNWRAPPED.set(True),
              delete_to_trash.TRASH.set(True))
    try:
        with pc.bind(_ctx(names)), permissions.asking_with(_no_card):
            assert (await _REAL["run_command"].execute({"command": "rm ../x"}))["ok"] is True
            monkeypatch.setattr(command_sandbox, "available", lambda: False)
            unconfined = await _REAL["run_command"].execute({"command": "ls"})
    finally:
        delete_to_trash.TRASH.reset(tokens[2])
        terminal_exec.UNWRAPPED.reset(tokens[1])
        terminal_exec.OUTSIDE_SANDBOX.reset(tokens[0])
    if names:
        [only] = ran
        assert (only["cwd"], only["sandbox"], only["unwrapped"]) == (ws / "sub" / "kid", True, False)
        assert ws in only["readable"] and trashed == []
        assert unconfined["executed"] is False and "the sandbox can't start here" in unconfined["error"]
    else:                                   # the commander's delete goes to the Trash, both times
        assert trashed == [ws, ws] and ran == []


async def test_a_sub_sessions_job_whose_context_names_no_folder_gets_none_not_the_workspace(ws):
    from server.db import session as db_session
    from server.services import background_jobs
    job = background_jobs.Job(job_id="job-kid", conversation_id="sub-kid", goal="g", acceptance=[], parent_id=ROOT)
    background_jobs._jobs[job.job_id] = job
    token = background_jobs._inside_job.set(job.job_id)
    try:
        async with db_session.AsyncSessionLocal() as db:
            assert settings_service.run_sub_folder() is None
            assert await settings_service.workspace_dir_for_run(db) is None
            assert await settings_service.workspace_dir(db) == ws          # reads keep the workspace
    finally:
        background_jobs._inside_job.reset(token)
        background_jobs._jobs.pop(job.job_id)


# -- the folder ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, name", [
    ("1b4e28ba", "1b4e28ba"), ("../../etc", "etc"), ("a/b", "a-b"), (".hidden", "hidden"), ("..", "sub"),
    ("x\x00y\x1b\nz", "x-y-z"), ("AbC", "abc"), ("ＡＢ", "ab"), ("-a-", "a"), ("", "sub"), ("a" * 100, "a" * 32),
    ("é", "sub"), ("a b\tc", "a-b-c"), ("x" * 31 + "/y", "x" * 31)])
def test_a_short_name_becomes_a_plain_bounded_folder_name(raw, name):
    assert sub_sessions.folder_name(raw) == name


async def test_names_are_unique_among_siblings_by_age_and_a_grandchilds_folder_is_inside_its_parents(
        runs, tmp_path):  # noqa: F811
    async with runs() as db:
        for cid in ("sub-cccccccc-1", "sub-CCCCCCCC-2", "sub-cccccccc-3", "sub-dddddddd-1"):
            await sub_sessions.create_child(db, ROOT, cid)
        await sub_sessions.create_child(db, "sub-CCCCCCCC-2", "sub-eeeeeeee-1")
        await db.commit()
    names = {cid: await sub_sessions.folder_names(cid) for cid in (
        "sub-cccccccc-1", "sub-CCCCCCCC-2", "sub-cccccccc-3", "sub-dddddddd-1", "sub-eeeeeeee-1")}
    assert names == {"sub-cccccccc-1": ("cccccccc",), "sub-CCCCCCCC-2": ("cccccccc-2",),
                     "sub-cccccccc-3": ("cccccccc-3",), "sub-dddddddd-1": ("dddddddd",),
                     "sub-eeeeeeee-1": ("cccccccc-2", "eeeeeeee")}
    ws = tmp_path.resolve()
    assert workspace_paths.sub_folder(ws, names["sub-eeeeeeee-1"]) == ws / "sub" / "cccccccc-2" / "sub" / "eeeeeeee"
    for cid in (ROOT, "c-nobody"):
        with pytest.raises(sub_sessions.SubSessionError):
            await sub_sessions.folder_names(cid)        # not a sub-session: no folder


def _planted(ws, out, how):
    if how == "sub is a link out":
        os.symlink(out, ws / "sub")
    elif how == "the folder is a link out":
        (ws / "sub").mkdir()
        os.symlink(out, ws / "sub" / "ab")
    elif how == "the folder is a link inside":
        (ws / "sub").mkdir()
        (ws / "other").mkdir()
        os.symlink(ws / "other", ws / "sub" / "ab")
    elif how == "sub is a link inside":
        (ws / "other").mkdir()
        os.symlink(ws / "other", ws / "sub")
    elif how == "a dangling link":
        (ws / "sub").mkdir()
        os.symlink(out / "missing", ws / "sub" / "ab")
    else:
        (ws / "sub").mkdir()
        (ws / "sub" / "ab").write_text("a file")


@pytest.mark.parametrize("how", ["sub is a link out", "the folder is a link out", "the folder is a link inside",
                                 "sub is a link inside", "a dangling link", "the folder is a file"])
def test_a_planted_folder_is_refused_never_followed_or_made_through(tmp_path, how):
    ws, out = (tmp_path / "ws"), (tmp_path / "out")
    ws.mkdir()
    out.mkdir()
    _planted(ws.resolve(), out, how)
    with pytest.raises((workspace_paths.PathEscape, OSError)):
        workspace_paths.sub_folder(ws, ("ab",))
    assert os.listdir(out) == []                   # nothing made outside on the way
    assert not (ws / "other" / "ab").exists()


def test_a_folder_spelled_differently_on_disk_is_refused(tmp_path):
    ws = tmp_path.resolve()
    (ws / "SUB").mkdir()
    if not (ws / "sub").exists():
        pytest.skip("this disk is case-sensitive: `sub` is a folder of its own")
    with pytest.raises(workspace_paths.PathEscape, match="spelled differently"):
        workspace_paths.sub_folder(ws, ("ab",))


def test_a_folder_inside_arslans_protected_folders_is_refused(tmp_path, monkeypatch):
    ws = tmp_path.resolve()
    monkeypatch.setattr(command_sandbox, "cap6b_folders", lambda plugin_folder=None: [ws / "sub"])
    with pytest.raises(workspace_paths.PathEscape, match="skills, plugins or data"):
        workspace_paths.sub_folder(ws, ("ab",))


@pytest.mark.parametrize("names", [("..",), ("a/b",), ("",), (" a",), (".",), ()])
def test_a_name_that_isnt_plain_is_refused_before_anything_is_made(tmp_path, names):
    with pytest.raises(workspace_paths.PathEscape, match="not a sub-session folder name"):
        workspace_paths.sub_folder(tmp_path, names)
    assert os.listdir(tmp_path) == []
