"""INB2 (v0.1.64, the user's item 7): "about you" memories Arslan writes (remember, memory_note's about_you)
take effect directly when the user is present, the whole conversation read nothing from outside, and the
text is ordinary. Anything else is a proposal with its reason, listed in Memory's "待整理", never in a
queue or the badge. A sensitive one gets one question in the chat line, bound to that proposal.

Presence is an allowlist (server/services/presence.py): the window's user_message and the iPhone's
chat.send (it arrives on the same socket with source "phone"). "Read outside content" is a per-run record
(`runs.read_outside`, migration 0072); a run with no record counts as having read some.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from server.db.migrations import runner
from server.db.migrations.versions import _0072_runs_read_outside as m0072
from server.db.companion_models import MemoryEntry
from server.db.models import MemoryProposal, Run
from server.orchestrator import run_trace, untrusted
from server.orchestrator.tool_caller import ToolCaller
from server.services import (background_jobs, host_run, memory_tools_v2, presence, proactive_service, run_recorder,
                             run_registry)
from server.services import personal_context as pc
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository

from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite

CID = "c-inb2"
HOST = ToolCaller(actor="host", spawn_id=None, conversation_id=CID)


@pytest.fixture
async def memory(execution_db, monkeypatch):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    frames = []
    monkeypatch.setattr(run_registry, "make_emit", lambda conversation_id: frames.append)
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda run_id: None)
    background_jobs._reset_for_tests()
    execution_db.frames = frames
    yield execution_db
    background_jobs._reset_for_tests()


def _ctx(run_id=None, cid=CID, **kw):
    return pc.TaskMemoryContext(task_id="inb2", run_id="r", conversation_id=cid, model_is_local=True,
                                source_run_id=run_id, **kw)


async def _run(db, *, read_outside, cid=CID) -> int:
    async with db() as session:
        row = Run(conversation_id=cid, user_message="earlier", status="completed", read_outside=read_outside)
        session.add(row)
        await session.commit()
        return row.id


async def _write(tool, text, *, present=True, outside=False, ctx=None, action=None, entry=None):
    """One write from Arslan's own turn: present (or not), this turn having read outside content (or not)."""
    token = untrusted.track_turn()
    try:
        if outside:
            untrusted.mark_external()
        with pc.bind(ctx or _ctx()), (presence.user_turn() if present else presence.not_present()):
            if tool == "remember":
                args = {"action": action or "append", "kind": "preference", "content": text}
                if entry is not None:
                    args.update(entry)
                return await memory_tools_v2.remember(args, HOST)
            args = {"action": action or "add", "set": "about_you", "text": text}
            if entry is not None:
                args.update(entry)
            return await memory_tools_v2.note(args, HOST)
    finally:
        untrusted.end_turn(token)


async def _reason(db, entry_id) -> str:
    async with db() as session:
        return (await session.scalars(select(MemoryProposal.reason).where(
            MemoryProposal.target_entry_id == entry_id))).one()


# -- takes effect -----------------------------------------------------------------------------------

@pytest.mark.parametrize("tool", ["remember", "memory_note"])
async def test_present_in_a_clean_conversation_an_ordinary_about_you_takes_effect(memory, tool):
    out = await _write(tool, "The user prefers short answers")
    assert out["ok"] is True and out["status"] == "active" and out["saved"] is True
    # Visible and undoable, like a fact noticed after a turn: the chat line reads "remembered … [Undo]".
    assert [(f["type"], f["entry_id"], f["version"]) for f in memory.frames] == [
        ("fact_saved", out["id"], out["version"])]


async def test_it_is_marked_as_arslans_about_you_and_follows_the_cloud_setting(memory):
    out = await _write("remember", "The user prefers short answers")
    assert (out["confirmation_kind"], out["use_policy"]) == ("arslan_about_you", "local_only")
    out = await _write("remember", "The user writes in British English", ctx=_ctx(cloud_memory_default=True))
    assert out["use_policy"] == "cloud_allowed"


async def test_another_conversation_reading_outside_content_does_not_matter(memory):
    await _run(memory, read_outside=True, cid="c-other")
    assert (await _write("remember", "The user prefers short answers"))["status"] == "active"


async def test_the_runs_own_row_is_not_counted_while_it_runs(memory):
    current = await _run(memory, read_outside=None)
    assert (await _write("remember", "The user prefers short answers", ctx=_ctx(current)))["status"] == "active"


# -- waits: read outside content ---------------------------------------------------------------------

@pytest.mark.parametrize("earlier", [True, None], ids=["turn-n-read-a-page", "a-run-with-no-record"])
async def test_an_earlier_turn_that_read_outside_content_keeps_about_you_waiting(memory, earlier):
    """Turn N read a page (or left no record: older than INB2, or it crashed); turn N+1 starts clean,
    and its "about you" still waits."""
    await _run(memory, read_outside=earlier)
    out = await _write("remember", "The user's company uses Jira")
    assert out["status"] == "proposed" and out["requires_confirmation"] is True
    assert await _reason(memory, out["id"]) == "external_seen"


async def test_this_turn_reading_outside_content_keeps_it_waiting(memory):
    out = await _write("memory_note", "The user's company uses Jira", outside=True)
    assert out["status"] == "proposed" and await _reason(memory, out["id"]) == "external_seen"


async def test_a_job_still_running_in_the_conversation_counts_as_outside(memory):
    """A job's run in the same conversation has no record until it ends."""
    await _run(memory, read_outside=None)
    assert (await _write("remember", "The user prefers tea"))["status"] == "proposed"


# -- waits: nobody present -----------------------------------------------------------------------------

async def test_a_turn_off_the_allowlist_keeps_about_you_waiting(memory):
    out = await _write("remember", "The user prefers short answers", present=False)
    assert out["status"] == "proposed" and await _reason(memory, out["id"]) == "not_present"


def test_presence_is_off_unless_an_allowlisted_entry_turns_it_on():
    assert presence.present() is False
    with presence.user_turn():
        assert presence.present() is True
        with presence.not_present():                 # a sub-session's run, inside a present turn
            assert presence.present() is False
        assert presence.present() is True
    assert presence.present() is False


async def test_a_background_job_reads_not_present_even_when_a_present_turn_started_it(memory, monkeypatch):
    """Through background_jobs.start, as a turn starts one: the job runs in a fresh context."""
    seen = []

    async def run(job):
        seen.append(presence.present())
    monkeypatch.setattr(background_jobs, "_run", run)
    with presence.user_turn():
        job = await background_jobs.start(CID, "tidy the notes", [], outside_seen=False)
    await job.task
    assert seen == [False]


# -- waits: sensitive, with the chat line's question ------------------------------------------------------

@pytest.mark.parametrize("text", [
    "The user's children go to school nearby", "The user's kids start at 8", "The user's parents live abroad",
    "The user's wife is a doctor", "The user's husband cooks", "The user's family visits on Sundays",
    "用户的孩子周三有钢琴课", "用户的父母住在老家", "用户的老婆是医生", "用户的家人周末来",
    "The user's home address is 1 Example Street",
])
async def test_a_sensitive_about_you_waits_and_the_chat_line_asks_about_that_one(memory, text):
    out = await _write("remember", text)
    assert out["status"] == "proposed" and await _reason(memory, out["id"]) == "sensitive"
    [frame] = memory.frames
    async with memory() as session:
        proposal = (await session.scalars(select(MemoryProposal).where(
            MemoryProposal.target_entry_id == out["id"]))).one()
    assert frame["type"] == "memory_proposed" and frame["proposal_id"] == proposal.id
    assert (frame["entry_id"], frame["version"], frame["content"], frame["reason"]) == (
        out["id"], out["version"], text, "sensitive")


@pytest.mark.parametrize("present,outside,reason", [
    (True, False, "sensitive"),
    (True, True, "external_seen"),
    (False, False, "not_present"),
])
async def test_a_sensitive_about_you_first_names_whatever_else_stopped_it(memory, present, outside, reason):
    """The chat line asks its one question (two buttons) only about a sensitive entry from the user's own
    present, clean turn. One that a turn which read outside content wrote, or that was written with nobody
    present, waits for that reason in 待整理, with no question in the chat: a page must never get a one-click
    keep under the reply."""
    out = await _write("remember", "The user's family visits on Sundays", present=present, outside=outside)
    assert out["status"] == "proposed" and await _reason(memory, out["id"]) == reason
    [frame] = memory.frames
    assert (frame["type"], frame["reason"], frame["sensitive"]) == ("memory_proposed", reason, True)


async def test_a_sensitive_fact_noticed_after_a_turn_names_its_proposal_in_the_chat_line(memory, monkeypatch):
    """The extractor's path too: its memory_proposed frame names the proposal, version, text and reason,
    so the chat line's two buttons answer exactly that proposal."""
    from server.services import turn_facts

    async def extract(conversation_id, user_message):
        return [{"content": "用户的孩子周三有钢琴课", "sensitive": False}]
    monkeypatch.setattr(turn_facts, "extract", extract)
    frames = []
    with pc.bind(_ctx(auto_activate_noticed=True)):
        assert await turn_facts.capture(CID, "我孩子周三有钢琴课", frames.append) == 1
    [frame] = [f for f in frames if f["type"] in {"memory_proposed", "fact_saved"}]
    async with memory() as session:
        proposal = (await session.scalars(select(MemoryProposal))).one()
    assert frame["type"] == "memory_proposed" and frame["entry_id"] == proposal.target_entry_id
    assert (frame["proposal_id"], frame["version"], frame["reason"]) == (proposal.id, proposal.target_version,
                                                                         "sensitive")


def test_a_child_process_is_not_family():
    """Bare "child" is left out of the word list on purpose: "child process" is ordinary."""
    from arslan.companion import memory as memory_module
    assert not memory_module.sensitive_words("The user's build spawns a child process per test")


# -- unchanged -------------------------------------------------------------------------------------------

async def test_a_supersede_and_a_note_replace_stay_proposals(memory):
    first = await _write("memory_note", "The user prefers short answers")
    assert first["status"] == "active"
    replaced = await _write("memory_note", "The user prefers very short answers", action="replace",
                            entry={"id": first["id"]})
    assert replaced["status"] == "proposed"


@pytest.mark.parametrize("flag", ["no_learning", "temporary"])
async def test_no_learning_and_temporary_still_refuse(memory, flag):
    out = await _write("remember", "The user prefers short answers", ctx=_ctx(**{flag: True}))
    assert out == {"ok": False, "code": "learning_disabled"}


async def test_the_badge_no_longer_counts_memory(memory):
    async with memory() as session:
        session.add(MemoryProposal(kind="memory_v2", table_name="memory_entries", reason="sensitive", status="pending"))
        await session.commit()
    assert "memory" not in await proactive_service.summary()


# -- #475 review: the whole run, and a conversation to check (F5, F7) ------------------------------------

async def test_an_earlier_turn_of_the_same_run_that_read_outside_content_keeps_it_waiting(memory):
    """F5: turn 1 of this run read a page; turn 2 starts clean, and this run has no record yet."""
    with run_trace.collecting():
        token = untrusted.track_turn()
        untrusted.mark_external()
        run_trace.record_outside(untrusted.end_turn(token))
        out = await _write("remember", "The user prefers short answers")
    assert out["status"] == "proposed" and await _reason(memory, out["id"]) == "external_seen"


async def test_with_no_conversation_to_check_about_you_waits(memory):
    """F7: nothing to check means nothing is known to be clean."""
    out = await _write("remember", "The user prefers short answers", ctx=_ctx(cid=None))
    assert out["status"] == "proposed"


async def test_a_remember_supersede_in_a_present_clean_turn_stays_a_proposal(memory):
    """F6: only a new entry takes effect directly; Arslan's edit of one waits, present and clean or not."""
    first = await _write("remember", "The user prefers short answers")
    assert first["status"] == "active"
    async with repository() as repo:
        row = await repo.db.get(MemoryEntry, first["id"])
        alias = await repo.compatibility_id(row, "user_facts")
    out = await _write("remember", "The user prefers very short answers", action="supersede",
                       entry={"target_id": alias, "expected_version": first["version"]})
    assert out["status"] == "proposed"
    assert await _entry(memory, first["id"]) == ("active", "normal", "local_only", "The user prefers short answers")


# -- #475 review: an existing entry is never changed by "about you" taking effect (F3) ---------------------

USER = MemoryActor(origin="user")


async def _entry(db, entry_id):
    from server.db.companion_models import MemoryRevision
    async with db() as session:
        row = await session.get(MemoryEntry, entry_id)
        revision = await session.get(MemoryRevision, row.current_revision_id)
        return row.status, row.sensitivity, row.use_policy, revision.content


async def _pending(db, entry_id) -> int:
    async with db() as session:
        return len((await session.scalars(select(MemoryProposal.id).where(
            MemoryProposal.target_entry_id == entry_id, MemoryProposal.status == "pending"))).all())


async def test_a_no_is_not_undone_by_a_later_clean_write_of_the_same_words(memory):
    waiting = await _write("remember", "The user prefers short answers", present=False)
    async with repository() as repo:
        await repo.resolve_proposal(waiting["proposal_id"], accept=False, actor=USER)
    assert (await _entry(memory, waiting["id"]))[0] == "paused"
    again = await _write("remember", "The user prefers short answers")
    assert again["id"] == waiting["id"]
    assert (await _entry(memory, waiting["id"]))[0] == "paused" and await _pending(memory, waiting["id"]) == 0


async def test_a_no_is_not_undone_by_the_same_fact_noticed_again(memory):
    """Not only "about you": the extractor noticing the same words again ("remember me" on) does not bring
    back what the user said no to. Only the user's own confirmation does."""
    fact = MemoryWrite(content="The user prefers short answers", kind="preference", scope=MemoryScope(kind="global"))
    async with repository() as repo:
        waiting = await repo.create(fact, MemoryActor(origin="extractor"))
        await repo.resolve_proposal(waiting["proposal_id"], accept=False, actor=USER)
    async with repository() as repo:
        await repo.create(fact, MemoryActor(origin="extractor", auto_activate_noticed=True))
    assert (await _entry(memory, waiting["id"]))[0] == "paused"
    async with repository() as repo:
        await repo.create(fact, USER)                       # the user adds it again in Memory: it comes back
    assert (await _entry(memory, waiting["id"]))[0] == "active"


async def test_a_waiting_entry_is_not_switched_on_by_a_clean_write_in_another_conversation(memory):
    waiting = await _write("remember", "The user rides to work", outside=True)
    elsewhere = await _write("remember", "The user rides to work", ctx=_ctx(cid="c-elsewhere"))
    assert elsewhere["id"] == waiting["id"]
    assert (await _entry(memory, waiting["id"]))[0] == "proposed" and await _pending(memory, waiting["id"]) == 1


async def test_a_sensitive_proposal_from_the_extractor_stays_waiting_and_sensitive(memory, monkeypatch):
    """The model marked the fact sensitive (no keyword says so); Arslan then writes the same words, present
    and clean. The extractor's proposal is still the user's to answer."""
    from server.services import turn_facts

    async def extract(conversation_id, user_message):
        return [{"content": "The user is pregnant", "sensitive": True}]
    monkeypatch.setattr(turn_facts, "extract", extract)
    with pc.bind(_ctx(auto_activate_noticed=True)):
        assert await turn_facts.capture(CID, "I'm pregnant", lambda frame: None) == 1
    [noticed] = [f for f in memory.frames if f.get("type") == "memory_proposed"] or [None]
    async with memory() as session:
        entry_id = (await session.scalars(select(MemoryEntry.id))).one()
    await _write("remember", "The user is pregnant")
    assert await _entry(memory, entry_id) == ("proposed", "sensitive", "local_only", "The user is pregnant")


async def test_arslan_never_widens_what_the_user_kept_for_this_mac_only(memory):
    """The user kept it sensitive and for this Mac only. Arslan's note adds the same words to "about you":
    the user's choice stays as it was."""
    async with repository() as repo:
        mine = await repo.create(MemoryWrite(content="The user is pregnant", kind="preference",
                                             scope=MemoryScope(kind="global"), sensitivity="sensitive",
                                             sensitive_acknowledged=True, use_policy="local_only"), USER)
    assert (mine["status"], mine["sensitivity"], mine["use_policy"]) == ("active", "sensitive", "local_only")
    await _write("memory_note", "The user is pregnant", ctx=_ctx(cloud_memory_allowed=True))
    assert await _entry(memory, mine["id"]) == ("active", "sensitive", "local_only", "The user is pregnant")
    assert await _pending(memory, mine["id"]) == 1         # putting it "in view" is an edit: it waits for the user


async def test_only_the_user_loosens_an_entry_anyone_else_revises(memory):
    """The extractor takes a waiting fact into effect ("remember me" on): it stays sensitive and for this Mac
    only, because only the user loosens an entry (#475 review, F3)."""
    async with repository() as repo:
        waiting = await repo.create(MemoryWrite(content="The user is pregnant", kind="preference",
                                                scope=MemoryScope(kind="global"), sensitivity="sensitive"),
                                    MemoryActor(origin="extractor"))
    assert waiting["status"] == "proposed"
    noticed = MemoryActor(origin="extractor", auto_activate_noticed=True, cloud_memory_allowed=True)
    async with repository() as repo:
        await repo.revise(waiting["id"], waiting["version"], MemoryWrite(
            content="The user is pregnant", kind="preference", scope=MemoryScope(kind="global")), noticed)
    assert await _entry(memory, waiting["id"]) == ("active", "sensitive", "local_only", "The user is pregnant")


async def test_the_chat_lines_no_is_refused_once_the_entry_changed(memory):
    """The chat line's two buttons name the version they showed: a "No" for an entry that changed since is
    refused (the line then points to Memory), and 待整理's own "No", which names none, works as before."""
    waiting = await _write("remember", "The user's family visits on Sundays")
    async with repository() as repo:
        await repo.revise(waiting["id"], waiting["version"],
                          MemoryWrite(content="The user's family visits on Saturdays", kind="preference",
                                      scope=MemoryScope(kind="global"), sensitive_acknowledged=True), USER)
    with pytest.raises(MemoryError, match="memory_version_conflict"):
        async with repository() as repo:
            await repo.resolve_proposal(waiting["proposal_id"], accept=False, actor=USER,
                                        expected_version=waiting["version"])
    assert await _pending(memory, waiting["id"]) == 1
    async with repository() as repo:
        await repo.resolve_proposal(waiting["proposal_id"], accept=False, actor=USER)
    assert await _pending(memory, waiting["id"]) == 0


# -- the run's record ------------------------------------------------------------------------------------

@pytest.mark.parametrize("outside,expected", [(True, True), (False, False)])
async def test_a_run_records_whether_it_read_outside_content(memory, outside, expected):
    async def body(emit):
        token = untrusted.track_turn()
        if outside:
            untrusted.mark_external()
        run_trace.record_outside(untrusted.end_turn(token))
        return "ok"
    await host_run.execute(CID, "hi", lambda e: None, body)
    async with memory() as session:
        assert (await session.scalars(select(Run.read_outside))).one() is expected


async def test_one_turn_of_a_run_that_read_outside_content_is_enough(memory):
    """A run with two turns (the OCR retry runs the turn again): the first read a page, the second did not;
    the run's record stays yes."""
    async def body(emit):
        for outside in (True, False):
            token = untrusted.track_turn()
            if outside:
                untrusted.mark_external()
            run_trace.record_outside(untrusted.end_turn(token))
        return "ok"
    await host_run.execute(CID, "hi", lambda e: None, body)
    async with memory() as session:
        assert (await session.scalars(select(Run.read_outside))).one() is True


async def test_a_run_whose_turn_never_ended_has_no_record(memory):
    async def body(emit):
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        await host_run.execute(CID, "hi", lambda e: None, body)
    async with memory() as session:
        assert (await session.scalars(select(Run.read_outside))).one() is None


async def test_a_real_turn_that_reads_a_page_records_it(memory, monkeypatch):
    """Through run_native: the tool loop hands the turn's mark to the run's record."""
    from arslan.models import LLMResponse
    from server.orchestrator import tool_loop
    from server.registry import executors

    class Page:
        async def execute(self, args):
            return {"ok": True, "url": args.get("url"), "content": "a page"}

    class Model:
        def __init__(self):
            self.replies = [LLMResponse(usage={}, content=None, tool_calls=[{"id": "c1", "type": "function",
                            "function": {"name": "web_extract", "arguments": {"url": "https://example.test"}}}]),
                            LLMResponse(usage={}, content="done", tool_calls=[])]

        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            return self.replies.pop(0) if self.replies else LLMResponse(usage={}, content="ok", tool_calls=[])

    async def tools():
        return [{"key": "web_extract", "description": "fixture"}]
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Model())
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", Page())

    async def body(emit):
        result = await tool_loop.run_native(system="INB2", user_content="read it", history=[], emit=lambda e: None,
                                            on_chunk=lambda c: None, resolve_tools=tools, conversation_id=CID,
                                            caller=HOST)
        return result.get("final")
    with pc.bind(_ctx()):
        await host_run.execute(CID, "read it", lambda e: None, body)
    async with memory() as session:
        assert (await session.scalars(select(Run.read_outside))).one() is True


# -- migration 0072 ---------------------------------------------------------------------------------------

def test_0072_adds_the_column_once_and_touches_nothing_else(tmp_path):
    import sqlalchemy as sa
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE runs (id INTEGER PRIMARY KEY, conversation_id VARCHAR(50) NOT NULL)")
        conn.exec_driver_sql("INSERT INTO runs (conversation_id) VALUES ('old')")
        conn.exec_driver_sql("CREATE TABLE memory_proposals (id INTEGER PRIMARY KEY, status VARCHAR(20))")
        conn.exec_driver_sql("INSERT INTO memory_proposals (status) VALUES ('pending')")
        m0072.upgrade_sync(conn)
        m0072.upgrade_sync(conn)
        columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(runs)")]
        assert columns.count("read_outside") == 1
        assert conn.exec_driver_sql("SELECT read_outside FROM runs").scalar() is None   # no record: outside
        assert conn.exec_driver_sql("SELECT status FROM memory_proposals").scalar() == "pending"
    assert ("0072", m0072.upgrade_sync) in runner.MIGRATIONS


def test_0072_leaves_a_database_without_runs_alone(tmp_path):
    import sqlalchemy as sa
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'n.db'}")
    with engine.begin() as conn:
        m0072.upgrade_sync(conn)


_ = datetime  # kept for fixtures that add timestamps
