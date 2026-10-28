"""INB2 (v0.1.64, the user's item 7): "about you" memories Arslan writes (remember, memory_note's about_you)
take effect directly when the user is present, the whole conversation read nothing from outside, and the
text is ordinary. Anything else is a proposal with its reason, listed in Memory's "待整理", never in a
queue or the badge. A sensitive one gets one question in the chat line, bound to that proposal.

Presence is an allowlist (server/services/presence.py): the window's user_message and the iPhone's
chat.send (it arrives on the same socket with source "phone"). "Read outside content" is a per-run record
(`runs.read_outside`, migration 0072); a run with no record counts as having read some.
"""
import contextvars
from datetime import datetime

import pytest
from sqlalchemy import select

from server.db.migrations import runner
from server.db.migrations.versions import _0072_runs_read_outside as m0072
from server.db.models import MemoryProposal, Run
from server.orchestrator import run_trace, untrusted
from server.orchestrator.tool_caller import ToolCaller
from server.services import (background_jobs, host_run, memory_tools_v2, presence, proactive_service, run_recorder,
                             run_registry)
from server.services import personal_context as pc
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync

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


async def test_a_background_job_reads_not_present_even_when_a_present_turn_started_it():
    seen = []

    async def job():
        seen.append(presence.present())
    import asyncio
    with presence.user_turn():
        await asyncio.get_running_loop().create_task(job(), context=contextvars.Context())
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
