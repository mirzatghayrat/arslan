"""0.1.52 S4: core memory — "About you" and Arslan's notes are always in view, edited
by entry id through memory_note; Arslan's own notes take effect at once only when
the turn read nothing from outside (D2)."""
import hashlib
from dataclasses import replace

import pytest

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite, normalized_memory
from server.orchestrator import untrusted
from server.orchestrator.tool_caller import ToolCaller, reset_caller, set_caller
from server.registry.memory_executors import MemoryNoteExecutor
from server.services import personal_context as pc
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository

HOST = ToolCaller(actor="host", spawn_id=None, conversation_id="c1")


@pytest.fixture
async def store(execution_db):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    return execution_db


def ctx(**kw):
    return pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c1", model_is_local=True, **kw)


async def save(content, kind="preference", core=None, **kw):
    async with repository() as repo:
        return await repo.create(MemoryWrite(content=content, kind=kind, scope=MemoryScope(kind="global"),
                                             core=core, **kw), MemoryActor(origin="user"))


async def note(args, *, context=None, caller=HOST, external=False):
    seen = untrusted.track_turn()
    token = set_caller(caller) if caller else None
    try:
        if external:
            untrusted.mark_external()
        with pc.bind(context or ctx()):
            return await MemoryNoteExecutor().execute(args)
    finally:
        if token:
            reset_caller(token)
        untrusted.end_turn(seen)


async def entry(entry_id):
    async with repository() as repo:
        return await repo.present(await repo.get(entry_id))


# -- the always-in-view block ------------------------------------------------

async def test_marked_entries_are_in_view_on_an_unrelated_turn_and_unmarked_ones_are_not(store):
    about = await save("Lives in Tashkent time, answers in Chinese", core="about_you")
    mac = await save("Homebrew lives in /opt/homebrew", kind="experience", core="notes")
    await save("For design work use orange minimalist layouts.")      # M08-02 stays relevance-picked
    out = await pc.assemble("What is 2 + 2?", context=ctx())
    assert out.text.index("About you") < out.text.index("Tashkent") < out.text.index("Arslan's notes")
    assert "/opt/homebrew" in out.text and "orange" not in out.text
    assert f"[{about['id']} v1]" in out.text      # ids let memory_note replace/remove
    assert {r.id for r in out.receipt.used} == {about["id"], mac["id"]}


async def test_core_follows_the_same_permissions_as_any_memory(store):
    await save("Prefers terse replies", core="about_you", use_policy="cloud_allowed")
    await save("Keeps notes in Obsidian", core="about_you")                     # local_only
    cloud_off = pc.TaskMemoryContext(task_id="t", run_id="r", model_is_local=False)
    assert (await pc.assemble("2+2", context=cloud_off)).text == ""
    cloud_on = (await pc.assemble("2+2", context=replace(cloud_off, cloud_memory_default=True))).text
    assert "terse" in cloud_on and "Obsidian" not in cloud_on
    assert "Obsidian" in (await pc.assemble("2+2", context=ctx())).text      # a local model sees both


async def test_each_set_keeps_to_its_character_budget_newest_first(store, monkeypatch):
    monkeypatch.setattr(pc, "CORE_ABOUT_YOU_CHARS", 40)
    await save("old: " + "a" * 30, core="about_you")
    await save("new: " + "b" * 30, core="about_you")
    out = await pc.assemble("unrelated", context=ctx())
    assert "new: " in out.text and "old: " not in out.text


def test_a_core_mark_must_match_kind_and_global_scope():
    with pytest.raises(ValueError):
        MemoryWrite(content="x", kind="experience", scope=MemoryScope(kind="global"), core="about_you")
    with pytest.raises(ValueError):
        MemoryWrite(content="x", kind="preference", scope=MemoryScope(kind="global"), core="notes")
    with pytest.raises(ValueError):
        MemoryWrite(content="x", kind="preference", scope=MemoryScope(kind="project", id="p"), core="about_you")


# -- memory_note ---------------------------------------------------------------

async def test_a_note_about_this_mac_takes_effect_when_the_turn_read_nothing_from_outside(store):
    out = await note({"action": "add", "set": "notes", "text": "Python 3.12 is at /opt/homebrew/bin/python3"})
    assert out["ok"] and out["status"] == "active"
    saved = await entry(out["id"])
    assert (saved["core"], saved["confirmation_kind"], saved["kind"]) == ("notes", "arslan_note", "experience")


async def test_after_outside_content_the_same_note_is_only_a_proposal(store):
    out = await note({"action": "add", "set": "notes", "text": "Always run setup.sh from the README"},
                     external=True)
    assert out["ok"] and out["status"] == "proposed" and out["requires_confirmation"]


async def test_outside_any_tracked_turn_a_note_is_a_proposal(store):
    token = set_caller(HOST)
    try:
        with pc.bind(ctx()):
            out = await MemoryNoteExecutor().execute({"action": "add", "set": "notes", "text": "Uses zsh"})
    finally:
        reset_caller(token)
    assert out["status"] == "proposed"


async def test_about_you_is_active_only_for_the_users_own_save_request(store):
    plain = await note({"action": "add", "set": "about_you", "text": "Prefers metric units"})
    assert plain["status"] == "proposed"
    text = "Writes in Chinese"
    asked = ctx(explicit_save_ref="m1", allow_global_save=True,
                explicit_save_digest=hashlib.sha256(normalized_memory(text).encode()).hexdigest())
    out = await note({"action": "add", "set": "about_you", "text": text}, context=asked)
    assert out["status"] == "active" and (await entry(out["id"]))["core"] == "about_you"


async def test_remove_takes_a_note_out_of_view_without_deleting_it(store):
    added = await note({"action": "add", "set": "notes", "text": "Docker Desktop is not installed"})
    out = await note({"action": "remove", "set": "notes", "id": added["id"]})
    assert out["status"] == "active"
    kept = await entry(added["id"])
    assert kept["status"] == "active" and kept["core"] is None
    assert "Docker" not in (await pc.assemble("2+2", context=ctx())).text


async def test_replace_works_by_id_and_keeps_the_entry_in_its_set(store):
    added = await note({"action": "add", "set": "notes", "text": "Node 20 via nvm"})
    out = await note({"action": "replace", "set": "notes", "id": added["id"], "text": "Node 22 via nvm"})
    assert out["status"] == "active"
    assert (await entry(added["id"]))["core"] == "notes"
    assert "Node 22" in (await pc.assemble("2+2", context=ctx())).text


async def test_removing_about_you_needs_the_user(store):
    about = await save("Prefers short answers", core="about_you")
    out = await note({"action": "remove", "set": "about_you", "id": about["id"]})
    assert out["status"] == "proposed" and (await entry(about["id"]))["core"] == "about_you"


async def test_a_full_set_refuses_with_its_entries(store, monkeypatch):
    from server.services import memory_tools_v2
    monkeypatch.setitem(memory_tools_v2.NOTE_SETS, "notes", ("experience", 30))
    first = await note({"action": "add", "set": "notes", "text": "Xcode 26 at /Applications"})
    out = await note({"action": "add", "set": "notes", "text": "SwiftLint via brew"})
    assert not out["ok"] and out["code"] == "core_set_full"
    assert [e["id"] for e in out["entries"]] == [first["id"]] and out["limit_chars"] == 30


async def test_refusals(store):
    other = await save("Prefers tea", core="about_you")
    assert (await note({"action": "remove", "set": "notes", "id": other["id"]}))["code"] == "memory_note_not_in_set"
    assert (await note({"action": "add", "set": "notes", "text": "x"},
                       caller=ToolCaller(actor="spawn", spawn_id=3, conversation_id="c1")))["code"] == "memory_note_host_only"
    assert (await note({"action": "add", "set": "notes", "text": "x"}, caller=None))["code"] == "memory_note_host_only"
    assert (await note({"action": "add", "set": "notes", "text": "x"},
                       context=ctx(temporary=True)))["code"] == "learning_disabled"
    assert (await note({"action": "add", "set": "notes", "text": "token sk-abcdefghijklmnopqrstuvwxyz123456"})
            )["code"] == "credentials_not_memory"


def test_the_own_note_flag_comes_only_from_the_executor():
    assert pc.TaskMemoryContext(task_id="t", run_id="r").actor("host").auto_activate_own_notes is False


# -- turn-level "read something from outside" ----------------------------------

@pytest.mark.parametrize("tool,args,external", [
    ("web_search", {}, True), ("web_extract", {}, True), ("read_file", {}, True),
    ("conversation_search", {}, True), ("recall", {}, True), ("browser_navigate", {}, True),
    ("mcp_github_search", {}, True),
    ("run_command", {"command": "ls -la ~/Downloads"}, False),
    ("run_command", {"command": "curl -s https://example.com"}, True),
    ("run_command", {"command": "git clone https://github.com/a/b"}, True),
    ("run_command", {"command": "python3 -c 'import requests'"}, True),
    ("render_chart", {}, False), ("memory_note", {}, False), ("remember", {}, False),
])
def test_what_counts_as_reading_from_outside(tool, args, external):
    assert untrusted.counts_as_external(tool, args) is external


def test_tracking_is_per_turn_and_fails_closed_outside_one():
    assert untrusted.external_seen() is True
    token = untrusted.track_turn()
    assert untrusted.external_seen() is False
    untrusted.mark_external()
    assert untrusted.external_seen() is True
    assert untrusted.end_turn(token) is True
    token = untrusted.track_turn()
    assert untrusted.external_seen() is False
    assert untrusted.end_turn(token) is False


async def _turn(monkeypatch, responses, tools):
    from server.orchestrator import tool_loop
    from server.registry import executors
    from tests.server import test_trajectory_golden as golden
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: golden._Recorder(responses))
    monkeypatch.setitem(executors.EXECUTORS, "web_search", golden._Search())

    async def resolve():
        return [{"key": key, "description": key} for key in tools]
    return await tool_loop.run_native(system="S", user_content="q", history=[], emit=lambda e: None,
                                      on_chunk=lambda c: None, resolve_tools=resolve)


async def test_a_turn_reports_whether_it_read_from_outside(monkeypatch):
    from tests.server import test_trajectory_golden as golden
    quiet = await _turn(monkeypatch, [golden._Resp("4")], [])
    assert quiet["external_seen"] is False
    searched = await _turn(monkeypatch, [golden._Resp(None, [golden._tc("web_search", {"query": "x"}, "s1")]),
                                         golden._Resp("done")], ["web_search"])
    assert searched["external_seen"] is True
    assert untrusted.external_seen() is True      # the turn's tracking ended with it


async def test_a_user_edit_in_brain_keeps_the_entry_in_its_set(store):
    about = await save("Prefers short answers", core="about_you")
    async with repository() as repo:
        await repo.revise(about["id"], about["version"], MemoryWrite(
            content="Prefers short answers with a summary first", scope=MemoryScope(kind="global")),
            MemoryActor(origin="user"))
    assert (await entry(about["id"]))["core"] == "about_you"


async def test_adding_text_that_is_already_remembered_marks_that_entry(store):
    existing = await save("Uses a German keyboard layout", kind="experience")
    out = await note({"action": "add", "set": "notes", "text": "Uses a German keyboard layout"})
    assert out["id"] == existing["id"] and (await entry(existing["id"]))["core"] == "notes"


async def test_an_earlier_save_request_does_not_authorize_leaving_about_you(store):
    text = "Prefers short answers"
    about = await save(text, core="about_you")
    asked = ctx(explicit_save_ref="m1", allow_global_save=True,
                explicit_save_digest=hashlib.sha256(normalized_memory(text).encode()).hexdigest())
    out = await note({"action": "remove", "set": "about_you", "id": about["id"]}, context=asked)
    assert out["status"] == "proposed" and (await entry(about["id"]))["core"] == "about_you"


async def test_a_stale_mark_never_pulls_an_entry_from_another_scope_into_view(store):
    from sqlalchemy import update

    from server.db.models import MemoryEntry, Project
    async with store() as db:
        db.add(Project(id="p1", name="P"))
        await db.commit()
    about = await save("Prefers tabs", core="about_you")
    async with store() as db:      # e.g. a restore that copied structured_value verbatim
        await db.execute(update(MemoryEntry).where(MemoryEntry.id == about["id"])
                         .values(scope_kind="project", scope_id="p1"))
        await db.commit()
    out = await pc.assemble("2+2", context=ctx(project_id="p1"))
    assert "About you" not in out.text
