"""SBX-5b (the user's "C lite", 2026-11-11): Arslan's file tools refuse the same named list of other apps' private data
the command sandbox closes (`command_sandbox.app_data_folders`), and nothing more; a once-only `app_data` card lets
one call through (a file tool) or re-runs one command with that one folder reopened read-only (`open_once`).

The kind is once only: never a grant or an "Always", never answered automatically or by the island, and with nobody
to ask it is refused and listed in the Inbox.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.db import session as db_session
from server.db.models import Setting
from server.orchestrator import command_gate, tool_loop
from server.orchestrator.turn_state import ToolTurn
from server.registry import file_tools
from server.services import approvals, hard_rules, permission_store, permissions, terminal_exec
from server.services.workspace_paths import AppData, PathEscape, resolve_for_read, resolve_in_workspace

CONV = "conv-sbx5b"


@pytest.fixture
def home(monkeypatch, tmp_path):
    home = (tmp_path / "home")
    home.mkdir()
    home = home.resolve()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("server.services.workspace_paths._home", lambda: home)
    (home / "Library/Messages").mkdir(parents=True)
    (home / "Library/Messages/chat.txt").write_text("private")
    (home / "Library/Application Support/Slack").mkdir(parents=True)
    (home / "Library/Application Support/Foo").mkdir(parents=True)
    (home / "Library/Application Support/Foo/config.txt").write_text("tool config")
    return home


# ── the check (workspace_paths), the same list as the sandbox ──────────────────────────

def test_a_listed_folder_is_refused_for_a_read_and_a_write_with_its_own_refusal(home):
    for where in ("~/Library/Messages/chat.txt", "~/Library/Messages", "~/Library/Application Support/Slack/x"):
        with pytest.raises(AppData) as held:
            resolve_for_read(where, [home], base=home)
        assert held.value.app in ("Messages", "Slack")
    with pytest.raises(AppData) as held:
        resolve_in_workspace("Library/Messages/new.txt", home, for_write=True, make_parents=True)
    assert (held.value.app, held.value.folder, held.value.path) == (
        "Messages", home / "Library/Messages", home / "Library/Messages/new.txt")
    with pytest.raises(AppData):
        resolve_in_workspace("Library/Messages/chat.txt", home)                    # edit_file's resolution
    assert isinstance(held.value, PathEscape)                     # every caller that refuses an escape refuses it


def test_through_a_link_and_in_another_letter_case_it_is_still_refused(home):
    (home / "Documents").mkdir()
    (home / "Documents/msgs").symlink_to(home / "Library/Messages", target_is_directory=True)
    for where in ("~/Documents/msgs/chat.txt",):
        with pytest.raises(AppData):
            resolve_for_read(where, [home], base=home)
    with pytest.raises(AppData):
        resolve_in_workspace("Library/MESSAGES/new.txt", home, for_write=True, make_parents=True)


def test_c_lite_an_unlisted_application_support_folder_is_not_refused(home):
    assert resolve_for_read("~/Library/Application Support/Foo/config.txt", [home], base=home) == \
        home / "Library/Application Support/Foo/config.txt"
    assert resolve_in_workspace("Library/Application Support/Foo/new.txt", home, for_write=True) == \
        home / "Library/Application Support/Foo/new.txt"
    assert resolve_for_read("~/Library", [home], base=home) == home / "Library"       # a parent is not an app's folder


def test_the_approved_path_passes_and_only_that_one(home):
    chat = home / "Library/Messages/chat.txt"
    assert resolve_for_read(str(chat), [home], app_data_ok=chat) == chat
    with pytest.raises(AppData):
        resolve_for_read(str(home / "Library/Messages"), [home], app_data_ok=chat)
    new = home / "Library/Messages/new.txt"
    assert resolve_in_workspace(str(new), home, for_write=True, app_data_ok=new) == new
    with pytest.raises(AppData):
        resolve_in_workspace(str(new), home, for_write=True, app_data_ok=chat)


# ── the kind (permissions, hard_rules) ──────────────────────────────────────────────

def test_the_kind_is_once_only_never_always_never_joined_never_auto_and_not_the_islands():
    assert "app_data" in permissions.KINDS
    assert "app_data" in permissions._ONCE_ONLY and "app_data" in permissions._NEVER_ALWAYS
    assert "app_data" in permissions._NEVER_JOINED
    assert "app_data" in hard_rules.NEVER_AUTO_KINDS and "app_data" not in hard_rules.MAY_AUTO_KINDS
    assert hard_rules.never_auto(permissions.Request(kind="app_data", target="x", title="t"))
    assert "app_data" not in approvals.ISLAND_KINDS
    frame = {"type": "propose_action", "kind": "app_data_file", "perm_kind": "app_data"}
    assert not approvals.island_may_answer(frame)


# ── the card, through the tool loop and the real executors ─────────────────────────────

@pytest.fixture
def db(execution_db, home):
    permission_store._reset_for_tests()
    approvals._reset_for_tests()
    yield execution_db
    approvals._reset_for_tests()


async def _home_workspace(home: Path) -> None:
    async with db_session.AsyncSessionLocal() as s:
        s.add(Setting(key="workspace_dir", value=str(home)))
        await s.commit()


async def _dispatch(key, args, *, confirm_workspace_write=None):
    async def tools():
        return [{"key": key, "description": key}]
    return await tool_loop._run_tool(key, args, "", ToolTurn(resolve_tools=tools, emit=lambda e: None,
                                     tool_timeout_s=5, tool_trace=[], convo=[], conversation_id=CONV,
                                     confirm_workspace_write=confirm_workspace_write))


class _Asker:
    def __init__(self, approved: bool, by: str | None = "mac"):
        self.frames: list[dict] = []
        self.answer = {"approved": approved, "by": by, "scope": "once", "note": ""}

    async def __call__(self, frame):
        self.frames.append(frame)
        return {**self.answer, "call_id": frame["call_id"]}


async def _yes_write(*_a, **_k):
    return True


async def test_a_read_asks_its_own_card_each_time_and_a_no_reads_nothing(db, home):
    await _home_workspace(home)
    yes = _Asker(True)
    with permissions.asking_with(yes):
        first = await _dispatch("read_file", {"path": "~/Library/Messages/chat.txt"})
        again = await _dispatch("read_file", {"path": "~/Library/Messages/chat.txt"})
        listed = await _dispatch("list_dir", {"path": "~/Library/Messages"})
    assert first["ok"] is True and first["content"] == "private" and again["ok"] is True
    assert listed["ok"] is True and [e["name"] for e in listed["entries"]] == ["chat.txt"]
    assert [f["perm_kind"] for f in yes.frames] == ["app_data"] * 3                  # no grant: asked each time
    assert all(f["options"] == ["once"] and f["kind"] == "app_data_file" and f["target"] == "Messages"
               for f in yes.frames)
    no = _Asker(False)
    with permissions.asking_with(no):
        refused = await _dispatch("read_file", {"path": "~/Library/Messages/chat.txt"})
    assert refused["ok"] is False and "content" not in refused


async def test_an_unlisted_folder_asks_nothing(db, home):
    await _home_workspace(home)

    async def no_card(frame):
        raise AssertionError(f"no card for an unlisted folder: {frame}")
    with permissions.asking_with(no_card):
        out = await _dispatch("read_file", {"path": "~/Library/Application Support/Foo/config.txt"})
    assert out["ok"] is True and out["content"] == "tool config"


async def test_a_write_asks_its_card_and_writes_only_that_path(db, home):
    await _home_workspace(home)
    yes = _Asker(True)
    with permissions.asking_with(yes):
        out = await _dispatch("write_file", {"path": "Library/Messages/note.txt", "content": "x"},
                              confirm_workspace_write=_yes_write)
    assert out["ok"] is True and (home / "Library/Messages/note.txt").read_text() == "x"
    assert [f["perm_kind"] for f in yes.frames] == ["app_data"]
    with permissions.asking_with(_Asker(False)):
        refused = await _dispatch("edit_file", {"path": "Library/Messages/note.txt", "old_string": "x",
                                                "new_string": "y"}, confirm_workspace_write=_yes_write)
    assert refused["ok"] is False and (home / "Library/Messages/note.txt").read_text() == "x"


async def test_one_click_is_one_call(db, home):
    """The click goes to that call's executor and is taken by it: an executor run again with no gate reads nothing."""
    await _home_workspace(home)
    with permissions.asking_with(_Asker(True)):
        out = await _dispatch("read_file", {"path": "~/Library/Messages/chat.txt"})
    assert out["ok"] is True
    gateless = await file_tools.ReadFileExecutor().execute({"path": "~/Library/Messages/chat.txt"})
    assert gateless["ok"] is False and gateless.get("code") == "app_data"
    file_tools.approve_app_data(home / "Library/Messages/chat.txt")              # a click whose executor never ran
    with permissions.asking_with(_Asker(False)):
        declined = await _dispatch("read_file", {"path": "~/Library/Messages/chat.txt"})
    assert declined["ok"] is False
    assert (await file_tools.ReadFileExecutor().execute({"path": "~/Library/Messages/chat.txt"}))["ok"] is False


async def test_with_nobody_to_ask_it_is_refused_and_listed(db, home):
    await _home_workspace(home)
    out = await _dispatch("read_file", {"path": "~/Library/Messages/chat.txt"})
    assert out["ok"] is False and "content" not in out
    async with db_session.AsyncSessionLocal() as s:
        rows = list(await permission_store.recent(s))
    assert [(r.kind, r.decision) for r in rows] == [("app_data", "deny")]


async def test_attach_file_refuses_a_listed_folder(db, home, monkeypatch):
    from server.services import execution_context
    await _home_workspace(home)
    monkeypatch.setattr(execution_context, "current_run_id", lambda: 1)
    out = await file_tools.AttachFileExecutor().execute({"path": "~/Library/Messages/chat.txt"})
    assert out["ok"] is False and "private data" in out["error"]


# ── the command card (command_gate) ─────────────────────────────────────────────────

async def _check(args, *, confirm=None):
    async def tools():
        return [{"key": "run_command", "description": "run_command"}]
    turn = ToolTurn(resolve_tools=tools, emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                    conversation_id=CONV, confirm_command=confirm)
    return await command_gate.check("run_command", args, turn)


@pytest.fixture
def confined(monkeypatch):
    from server.services import command_sandbox
    monkeypatch.setattr(command_sandbox, "available", lambda: True)

    async def on():
        return True
    monkeypatch.setattr(command_gate, "_sandbox_enabled", on)


async def _yes_command(*_a, **_k):
    return True


async def test_a_command_asks_to_reopen_the_one_listed_folder_read_only(db, home, confined):
    yes = _Asker(True)
    with permissions.asking_with(yes):
        plan = await _check({"command": "cat ~/Library/Messages/chat.txt", "app_data_once": "~/Library/Messages/x"},
                            confirm=_yes_command)
    assert isinstance(plan, command_gate.CommandPlan), plan
    assert plan.open_once == home / "Library/Messages"                    # the app's listed folder, not the path
    assert [(f["perm_kind"], f["kind"], f["target"], f["options"]) for f in yes.frames] == [
        ("app_data", "app_data_command", "Messages", ["once"])]
    with permissions.asking_with(_Asker(False)):
        refused = await _check({"command": "cat ~/Library/Messages/chat.txt", "app_data_once": "~/Library/Messages"},
                               confirm=_yes_command)
    assert isinstance(refused, dict) and refused["ok"] is False
    plain = await _check({"command": "ls"}, confirm=_yes_command)
    assert isinstance(plain, command_gate.CommandPlan) and plain.open_once is None


async def test_a_command_naming_an_unlisted_folder_is_refused_before_any_card(db, home, confined):
    async def no_card(frame):
        raise AssertionError(frame)
    with permissions.asking_with(no_card):
        out = await _check({"command": "ls", "app_data_once": "~/Library/Application Support/Foo"},
                           confirm=_yes_command)
    assert isinstance(out, dict) and out["ok"] is False and "isn't one of" in out["error"]


async def test_a_command_card_with_nobody_to_ask_is_refused_and_listed(db, home, confined):
    out = await _check({"command": "cat ~/Library/Messages/chat.txt", "app_data_once": "~/Library/Messages"})
    assert isinstance(out, dict) and out["ok"] is False
    async with db_session.AsyncSessionLocal() as s:
        rows = list(await permission_store.recent(s))
    assert ("app_data", "deny") in [(r.kind, r.decision) for r in rows]


def test_a_stopped_command_that_named_a_listed_folder_is_told_how_to_ask(home):
    result = {"ok": False, "exit_code": 1, "stdout": "", "cwd": str(home), "sandbox": "workspace",
              "stderr": f"cat: {home}/Library/Messages/chat.txt: Operation not permitted", "error": "exit code 1"}
    out = terminal_exec.explain(result, cwd=home, closed=[], mode="workspace", timed_out=False,
                                command="cat ~/Library/Messages/chat.txt")
    assert "app_data_once" in out["note"] and "Messages" in out["note"]
