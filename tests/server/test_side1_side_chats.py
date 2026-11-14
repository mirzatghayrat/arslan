"""SIDE-1 (v0.1.64, card docs/plans/0164/SIDE-side-chat.md): side chats, the backend.

A side chat is a conversation of its own under the one it was branched from. Each rule below has a test that goes red
without it:
- it reads its parent up to the branch, then its own messages, and nothing of it reaches the parent;
- it is shown, and may call, five read-only tools only: a list, kept where each tool's traits still say it reads;
- it starts marked as having read outside content unless every parent run up to the branch recorded none and nothing it
  reads is framed as outside content; one that started marked starts every turn marked;
- no job starts in it (an Inbox item accepted into it included), it reads memory as its parent does but writes no
  memory and no lesson, and none of its
  settings, its model or a pin can be set on it;
- a local-only receipt of its parent stops a cloud model in it, as one of its own would;
- it is in no list of conversations and not on the phone, and it goes with its parent.
"""
import asyncio
import re
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from arslan.companion.memory import MemoryError
from arslan.models import LLMResponse
from server.db.companion_models import ConversationContext, ContextReceiptRecord, MemorySuppression, Project
from server.db.models import ArslanMessage, ArslanSummary, ProactiveItem, ProviderConfig, Run
from server.orchestrator import arslan, memory, tool_loop, untrusted
from server.registry import tool_defs
from server.registry.tool import Traits
from server.services import background_jobs, phone_ids, sub_sessions, task_context
from tests.server import test_trajectory_golden as golden
from tests.server.test_q1a_quick_ask import _Model

PARENT = "c-parent"
FIVE = ["list_dir", "read_file", "search_files", "web_extract", "web_search"]
T0 = datetime(2026, 11, 14, 9)
NO_ROW = "side-0b7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b"


@pytest.fixture(autouse=True)
def _fresh():
    for module in (sub_sessions, background_jobs):
        module._reset_for_tests()
    yield
    for module in (sub_sessions, background_jobs):
        module._reset_for_tests()


async def _say(db, cid, text, *, role="user", minutes=0, run_id=None) -> int:
    async with db() as session:
        row = ArslanMessage(conversation_id=cid, role=role, content=text, run_id=run_id,
                            timestamp=T0 + timedelta(minutes=minutes))
        session.add(row)
        await session.commit()
        return row.id


async def _run(db, cid, read_outside, *, minutes=0) -> int:
    async with db() as session:
        run = Run(conversation_id=cid, user_message="x", status="completed", read_outside=read_outside,
                  started_at=T0 + timedelta(minutes=minutes))
        session.add(run)
        await session.commit()
        return run.id


async def _talk(db, cid=PARENT) -> list[int]:
    """Two turns of the parent, a minute apart: the ids of [question, answer, question, answer]."""
    turns = [("user", "first question"), ("arslan", "first answer"), ("user", "second question"),
             ("arslan", "second answer")]
    return [await _say(db, cid, text, role=role, minutes=n) for n, (role, text) in enumerate(turns)]


async def _start(db, parent=PARENT, branch=None) -> dict:
    """What POST /conversations/{parent}/side-chats does."""
    from server.services import side_chats
    async with db() as session:
        return await side_chats.create(session, parent, branch)


async def _refused(db, parent=PARENT, branch=None) -> tuple[int, str]:
    from server.services import side_chats
    with pytest.raises(side_chats.SideChatError) as refused:
        await _start(db, parent, branch)
    return refused.value.status, refused.value.code


async def _row(db, cid):
    async with db() as session:
        return await session.get(ConversationContext, cid)


def _capture(monkeypatch) -> dict:
    """What a chat turn hands the tool loop: the tools shown and callable, its notes, and whether it starts marked."""
    seen = {}

    async def run_native(*, resolve_tools, resolve_callable, on_chunk, turn_notes=None, **kw):
        seen["shown"] = sorted(tool["key"] for tool in await resolve_tools())
        seen["callable"] = sorted(tool["key"] for tool in await resolve_callable())
        seen["notes"] = list(turn_notes or [])
        seen["marked"] = bool((untrusted._CARRIED.get() or {}).get("seen"))
        on_chunk("ok")
        return {"final": "ok", "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    return seen


# -- migration 0099 ----------------------------------------------------------------------------------------------

def test_0099_adds_the_branch_and_the_mark_once_and_leaves_a_database_without_the_table_alone(tmp_path):
    from server.db.migrations.versions import _0099_side_chats as m0099
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE conversation_contexts (id VARCHAR(100) PRIMARY KEY, version INTEGER)")
            conn.exec_driver_sql("INSERT INTO conversation_contexts (id, version) VALUES ('c-1', 3)")
            m0099.upgrade_sync(conn)
            m0099.upgrade_sync(conn)
            columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversation_contexts)")]
            row = conn.exec_driver_sql("SELECT * FROM conversation_contexts").one()
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE conversation_contexts")
            m0099.upgrade_sync(conn)
            assert conn.exec_driver_sql("SELECT name FROM sqlite_master").all() == []
    finally:
        engine.dispose()
    assert columns == ["id", "version", "branch_message_id", "outside_at_start"]
    assert tuple(row) == ("c-1", 3, None, None)


def test_0099_comes_after_0095_and_an_install_at_the_previous_head_gets_it(tmp_path, monkeypatch):
    """0099 is the last migration, after 0095 (0096-0098 are reserved). An install whose ledger ends at the previous
    head gets it, and only it, at its next boot."""
    from server.db.migrations import runner
    from server.db.models import Base
    versions = [version for version, _ in runner.MIGRATIONS]
    assert versions[-2:] == ["0095", "0099"] and runner.head() == "0099"
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'arslan.db'}")
    try:
        Base.metadata.create_all(engine)
        with monkeypatch.context() as patched:
            patched.setattr(runner, "MIGRATIONS", runner.MIGRATIONS[:-1])
            with engine.begin() as conn:
                assert runner.apply_pending(conn)[-1] == "0095"
        with engine.begin() as conn:
            assert runner.apply_pending(conn) == ["0099"]
    finally:
        engine.dispose()


# -- making one --------------------------------------------------------------------------------------------------

async def test_a_side_chat_is_its_own_conversation_under_its_parent_at_its_newest_message(execution_db):
    ids = await _talk(execution_db)
    made = await _start(execution_db)
    assert re.fullmatch(r"side-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                        made["conversation_id"])
    assert (made["parent_id"], made["branch_message_id"], made["message_count"]) == (PARENT, ids[-1], 0)
    row = await _row(execution_db, made["conversation_id"])
    assert (row.kind, row.parent_id, row.branch_message_id) == ("side", PARENT, ids[-1])
    # Learning off on its own row; memory and the rest are read through its parent, never copied.
    assert (row.no_memory, row.no_learning, row.temporary, row.project_id) == (False, True, False, None)
    assert (row.cloud_memory_allowed, row.allow_sensitive, row.pinned) == (False, False, False)


async def test_a_blank_one_branches_at_the_newest_message_its_parent_would_read(execution_db):
    ids = await _talk(execution_db)
    async with execution_db() as session:
        session.add(MemorySuppression(source_kind="message_id", source_id=str(ids[-1]), entry_id="e",
                                      cutoff_at=T0 + timedelta(hours=1)))
        await session.commit()
    assert (await _start(execution_db))["branch_message_id"] == ids[-2]


@pytest.mark.parametrize("kind", ["quick", "sub", "side", "phone-made"])
async def test_only_an_ordinary_conversation_gets_one(execution_db, kind):
    """⓪Plan (2026-11-14): no side chat of a sub-session, nor of a quick question or of another side chat."""
    other = "phone-6c7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b" if kind == "phone-made" else "c-other"
    if kind != "phone-made":                    # one the phone made with no kind stored reads as a quick question
        async with execution_db() as session:
            session.add(ConversationContext(id=other, kind=kind, parent_id=None if kind == "quick" else PARENT))
            await session.commit()
    await _say(execution_db, other, "hello")
    assert await _refused(execution_db, other) == (422, "side_chat_parent_kind")


async def test_what_else_it_refuses(execution_db):
    ids = await _talk(execution_db)
    elsewhere = await _say(execution_db, "c-elsewhere", "another conversation's message")
    assert await _refused(execution_db, branch=elsewhere) == (422, "invalid_branch_message")
    assert await _refused(execution_db, branch=ids[-1] + 100) == (422, "invalid_branch_message")
    assert await _refused(execution_db, "c-nothing-said") == (409, "side_chat_nothing_to_read")
    async with execution_db() as session:
        session.add(ConversationContext(id="c-temporary", temporary=True))
        await session.commit()
    await _say(execution_db, "c-temporary", "hello")
    assert await _refused(execution_db, "c-temporary") == (422, "side_chat_from_temporary")
    sub_sessions._deleted.add(PARENT)           # a delete of it has begun in this process
    assert await _refused(execution_db) == (404, "not_found")
    sub_sessions._deleted.clear()
    async with execution_db() as session:
        await sub_sessions.tombstone(session, [PARENT])
        await session.commit()
    assert await _refused(execution_db) == (404, "not_found")


async def test_the_routes_start_and_list_them(client):
    ids = await _talk(client.db_maker)
    url = f"/api/v1/conversations/{PARENT}/side-chats"
    first = await client.post(url, json={"branch_message_id": ids[1]})
    assert first.status_code == 201
    first = first.json()
    assert (first["parent_id"], first["branch_message_id"], first["outside_at_start"]) == (PARENT, ids[1], False)
    second = await client.post(url, json={})
    assert second.status_code == 201 and second.json()["branch_message_id"] == ids[-1]
    # The quote the user selected is no field: it is the side chat's first message (⓪Plan, 2026-11-14).
    assert (await client.post(url, json={"quote": "first answer"})).status_code == 422
    assert (await client.post(url, json={"branch_message_id": ids[-1] + 50})).json()["detail"] == {
        "code": "invalid_branch_message"}
    await _say(client.db_maker, first["conversation_id"], "what did it mean?", minutes=10)
    listed = (await client.get(url)).json()
    assert [(item["conversation_id"], item["message_count"]) for item in listed] == [
        (first["conversation_id"], 1), (second.json()["conversation_id"], 0)]
    assert listed[0]["last_at"].startswith("2026-11-14T09:10")
    assert (await client.get("/api/v1/conversations/c-never-branched/side-chats")).json() == []


# -- what it reads ------------------------------------------------------------------------------------------------

async def test_it_reads_its_parent_up_to_the_branch_then_its_own_messages(execution_db):
    """Not a later parent message, not a summary that folds one in, not a message the user had suppressed."""
    m = [await _say(execution_db, PARENT, f"parent {n}", role="user" if n % 2 == 0 else "arslan", minutes=n)
         for n in range(6)]
    async with execution_db() as session:
        session.add_all([
            ArslanSummary(conversation_id=PARENT, summary="the summary up to parent 1", up_to_message_id=m[1]),
            ArslanSummary(conversation_id=PARENT, summary="the summary up to parent 4", up_to_message_id=m[4]),
            MemorySuppression(source_kind="message_id", source_id=str(m[2]), entry_id="e",
                              cutoff_at=T0 + timedelta(hours=1))])
        await session.commit()
    side = (await _start(execution_db, branch=m[3]))["conversation_id"]
    await _say(execution_db, side, "side question", minutes=10)
    ctx = await memory.assemble_working_context(side, budget=100_000)
    assert ctx["summary"] == "the summary up to parent 1"
    assert [item["content"] for item in ctx["history"]] == ["parent 3", "side question"]
    # Nothing of it reaches the parent: its context and what the window's socket sends for it.
    from server.ws import arslan as ws_arslan
    assert "side question" not in repr(await memory.assemble_working_context(PARENT, budget=100_000))
    assert "side question" not in repr(await ws_arslan._history(PARENT))


async def test_a_side_turn_runs_end_to_end_on_its_parents_part(execution_db, monkeypatch):
    """Through the window's path (the turn's task checks, before each model request, that what it read is still
    there: the parent's part is checked as the parent's). It runs on its parent's part, and learns nothing."""
    from server.services.memory_activation import activate_sync
    from server.services.memory_migration import migrate_legacy_sync
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    ids = await _talk(execution_db)
    side = (await _start(execution_db, branch=ids[1]))["conversation_id"]
    sent = []

    class Adapter:
        async def chat(self, system, user, **kwargs):
            await save("before_model")          # as every provider does first: where the turn checks what it read
            sent.append(repr((system, user, kwargs)))
            return LLMResponse(content="It meant the first one.", usage={}, tool_calls=[])
    from arslan.execution_checkpoint import save
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    events = []

    async def chat_card(command, argv, **kw):
        raise AssertionError("no card in a side chat")
    await arslan.handle_user_message(side, "what did that mean?", events.append, confirm_command=chat_card)
    await asyncio.gather(*list(arslan._AFTER_TURN))
    assert len(sent) == 1, events
    assert "first question" in sent[0] and "first answer" in sent[0] and "second question" not in sent[0]
    async with execution_db() as session:
        said = (await session.execute(select(ArslanMessage.content).where(
            ArslanMessage.conversation_id == side).order_by(ArslanMessage.id))).scalars().all()
        run = (await session.execute(select(Run).where(Run.conversation_id == side))).scalar_one()
        parents = (await session.execute(select(ArslanMessage.id).where(ArslanMessage.conversation_id == PARENT)
                                         )).scalars().all()
    assert said[0] == "what did that mean?" and said[-1].startswith("It meant the first one.")
    assert run.no_learning is True and parents == ids


# -- the outside-content mark (card, rule 3) ---------------------------------------------------------------------

@pytest.mark.parametrize("runs, marked", [
    ([], False), ([False, False], False), ([False, None], True), ([False, True], True),
], ids=["no-runs", "every-run-clean", "a-run-with-no-record", "a-run-read-outside"])
async def test_it_starts_marked_unless_every_parent_run_up_to_the_branch_recorded_none(execution_db, runs, marked):
    """No record (NULL) is a run still going, one that crashed, or one from before 0072: it counts as read."""
    await _talk(execution_db)
    for n, read in enumerate(runs):
        await _run(execution_db, PARENT, read, minutes=n)
    made = await _start(execution_db)
    assert made["outside_at_start"] is marked
    assert (await _row(execution_db, made["conversation_id"])).outside_at_start is marked


async def test_a_run_after_the_branch_leaves_it_clean(execution_db):
    ids = await _talk(execution_db)
    await _run(execution_db, PARENT, False)
    await _run(execution_db, PARENT, True, minutes=30)          # a later turn read a web page
    assert (await _start(execution_db, branch=ids[1]))["outside_at_start"] is False


async def test_a_run_a_message_up_to_the_branch_names_counts_whenever_it_started(execution_db):
    run = await _run(execution_db, PARENT, True, minutes=99)    # its start reads later than the branch
    await _say(execution_db, PARENT, "a question")
    answer = await _say(execution_db, PARENT, "an answer", role="arslan", minutes=1, run_id=run)
    assert (await _start(execution_db, branch=answer))["outside_at_start"] is True


@pytest.mark.parametrize("framed", ["job-result", "summary"])
async def test_text_framed_as_outside_content_in_what_it_reads_marks_it(execution_db, framed):
    """A background job's result is posted with no run of its own, and a summary folding one in keeps its frame."""
    ids = await _talk(execution_db)
    if framed == "job-result":
        found = await _say(execution_db, PARENT, untrusted.job_result("what the job found"), role="arslan", minutes=5)
        assert (await _start(execution_db, branch=ids[-1]))["outside_at_start"] is False    # after the branch
        assert (await _start(execution_db, branch=found))["outside_at_start"] is True
    else:
        async with execution_db() as session:
            session.add(ArslanSummary(conversation_id=PARENT, summary=f"{untrusted.SUMMARY_FROM_OUTSIDE}\nGoal: x",
                                      up_to_message_id=ids[1]))
            await session.commit()
        assert (await _start(execution_db))["outside_at_start"] is True


@pytest.mark.parametrize("stored, marked", [(False, False), (True, True), (None, True)],
                         ids=["started-clean", "started-marked", "no-record"])
async def test_every_turn_of_one_that_started_marked_starts_marked(execution_db, monkeypatch, stored, marked):
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"]
    async with execution_db() as session:
        (await session.get(ConversationContext, side)).outside_at_start = stored
        await session.commit()
    seen = _capture(monkeypatch)
    await arslan._handle_answer(side, "what did it mean?", lambda e: None)
    assert seen["marked"] is marked


async def test_what_it_brings_back_is_marked_when_it_read_outside_content(execution_db):
    """SIDE-2's seam: "Bring back to main" carries the mark into that main turn when this says so."""
    from server.services import side_chats
    await _talk(execution_db)
    clean = (await _start(execution_db))["conversation_id"]
    async with execution_db() as session:
        assert await side_chats.carries_outside(session, clean) is False
    await _run(execution_db, clean, None, minutes=20)           # its own turn, still running
    await _run(execution_db, PARENT, True, minutes=2)
    marked = (await _start(execution_db))["conversation_id"]
    async with execution_db() as session:
        assert await side_chats.carries_outside(session, clean) is True
        assert await side_chats.carries_outside(session, marked) is True
        assert await side_chats.carries_outside(session, NO_ROW) is True


# -- tools: the five, and nothing else (hole 1, `_answer_dispatch`) --------------------------------------------------

async def test_a_side_chat_is_shown_and_may_call_exactly_five_read_only_tools(execution_db, monkeypatch):
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"]
    seen = _capture(monkeypatch)
    await arslan._handle_answer(side, "what did it mean?", lambda e: None, source="phone")
    assert seen["shown"] == FIVE and seen["callable"] == FIVE
    assert arslan.SIDE_NOTE in seen["notes"] and arslan.PHONE_NOTE not in seen["notes"]


def test_each_of_the_five_reads_and_reading_alone_is_not_the_rule():
    """Their traits, pinned. 23 tools say they read, among them the shared browser, Hands' look and the plan."""
    assert all(tool_defs.TRAITS[key].effect == "read" for key in FIVE)
    assert {"browser_open", "desktop_look", "update_plan", "recall"} <= tool_defs.named(
        lambda traits: traits.effect == "read")


async def test_a_member_whose_traits_stop_saying_it_reads_is_dropped(execution_db, monkeypatch):
    monkeypatch.setitem(tool_defs.TRAITS, "list_dir", Traits(
        effect="local_write", parallel=False, outside=False, replay_safe=False, saves=False))
    assert sorted(tool["key"] for tool in await arslan._side_tools()) == [k for k in FIVE if k != "list_dir"]


#: A call to every other kind of tool: run directly, or through use_tool and find_tools; commands, writes, memory,
#: past conversations, jobs, schedules, sub-sessions, the shared browser, Hands, a choice card, a file, MCP.
OUTSIDE_THE_FIVE = [
    ("run_command", {"command": "touch x", "argv": ["touch", "x"]}),
    ("use_tool", {"name": "run_command", "arguments": {"command": "ls", "argv": ["ls"]}}),
    ("use_tool", {"name": "write_file", "arguments": {"path": "a.txt", "content": "x"}}),
    ("find_tools", {"query": "write a file"}),
    ("write_file", {"path": "a.txt", "content": "x"}),
    ("edit_file", {"path": "a.txt", "old_string": "x", "new_string": "y"}),
    ("remember", {"action": "append", "kind": "fact", "content": "the user likes tea"}),
    ("memory_note", {"action": "add", "set": "about_you", "text": "x"}),
    ("recall", {"query": "tea"}),
    ("conversation_search", {"query": "tea"}),
    ("schedule_task", {"name": "x", "prompt": "x", "when": "every: 3600"}),
    ("start_background_work", {"goal": "x", "criteria": []}),
    ("start_sub_session", {"brief": "x"}),
    ("browser_open", {"url": "https://example.com"}),
    ("desktop_look", {}),
    ("update_plan", {"items": ["a"]}),
    ("ask_user_choice", {"question": "q?", "options": [{"label": "a"}, {"label": "b"}]}),
    ("attach_file", {"path": "a.txt"}),
    ("mcp_1__anything", {}),
    ("escalate", {"kind": "data", "need": "x"}),
]


async def test_a_side_turn_runs_nothing_outside_the_five_and_asks_nothing(execution_db, monkeypatch):
    """The model names every other kind of tool anyway: each is refused before any executor or card. One of the five
    goes through to its executor."""
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"]
    calls = [*OUTSIDE_THE_FIVE, ("list_dir", {"path": "~"})]
    model = _Model([golden._Resp(tool_calls=[golden._tc(name, args, cid=f"c{i}") for i, (name, args) in
                                             enumerate(calls)]), golden._Resp(content="ok")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    golden._pin_workspace(monkeypatch)
    resolved, asked, events = [], [], []

    async def resolve_executor(key):
        resolved.append(key)
        return None
    monkeypatch.setattr(tool_loop, "resolve_executor", resolve_executor)

    async def ask(*args, **kwargs):
        asked.append(args)
        return True
    ask.ask_capability = ask
    await arslan._handle_answer(side, "look around", events.append, confirm_command=ask,
                                confirm_workspace_write=ask, confirm_schedule=ask)
    assert len(model.shown) == 2 and all(shown == FIVE for shown in model.shown), model.shown
    assert resolved == ["list_dir"] and asked == []
    assert not [e for e in events if e.get("type") in ("command_confirm", "approval_needed", "clarify_options")]


# -- no job in it (hole 3, `sub_sessions.refusal`) ------------------------------------------------------------------

async def test_an_inbox_item_accepted_into_a_side_chat_is_refused_and_nothing_is_claimed(client, monkeypatch):
    """Its job would run there with every background tool: memory, commands, writes."""
    from server.services import proactive_service

    async def configured():
        return True
    monkeypatch.setattr(proactive_service, "model_configured", configured)
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    async with client.db_maker() as session:
        item = ProactiveItem(kind="job_followup", fingerprint="fp:side", source_key="job:side",
                             title_key="title.job_followup", evidence=[{"key": "x", "params": {}}],
                             goal="Tidy the downloads folder")
        session.add(item)
        await session.commit()
    for target in (side, NO_ROW):
        got = await client.post(f"/api/v1/proactive/items/{item.id}/accept", json={"conversation_id": target})
        assert got.status_code == 422 and got.json()["detail"] == {"code": "side_chat_read_only"}, target
    async with client.db_maker() as session:
        assert (await session.get(ProactiveItem, item.id)).status == "new"
    assert background_jobs._jobs == {}


@pytest.mark.parametrize("made", [True, False], ids=["side-chat", "side-id-with-no-row"])
async def test_no_caller_starts_a_job_in_a_side_chat(execution_db, made):
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"] if made else NO_ROW
    with pytest.raises(sub_sessions.SubSessionError, match="side_chat_read_only"):
        await background_jobs.start(side, "Tidy the downloads folder", [], outside_seen=False)
    assert background_jobs._jobs == {}


# -- the parent's local-only receipts count (hole 4, `task_context.load`) ---------------------------------------------

async def test_a_local_only_receipt_of_the_parent_stops_a_cloud_model_in_the_side_chat(execution_db, monkeypatch):
    """Its history is its parent's up to the branch, which a local model wrote with local-only memory in view."""
    from server.services import llm_factory
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"]
    async with execution_db() as session:
        session.add(ContextReceiptRecord(
            id="local-receipt", conversation_id=PARENT, task_id="t", run_id="r",
            receipt={"memory_mode": "normal", "cloud_use": "not_sent", "local_only_used": True,
                     "used": [{"kind": "memory", "id": "m", "revision": 1}]}))
        await session.commit()

    async def cloud(db):
        return False
    monkeypatch.setattr(llm_factory, "memory_models_are_local", cloud)
    with pytest.raises(MemoryError, match="conversation_local_history"):
        await task_context.load(side, user_message="go on")

    async def local(db):
        return True
    monkeypatch.setattr(llm_factory, "memory_models_are_local", local)
    assert (await task_context.load(side, user_message="go on")).model_is_local is True


# -- reads memory, writes none (card, rule 4; the user's ruling, 2026-11-14) -----------------------------------------

async def test_its_turn_reads_memory_as_its_parent_does(execution_db, monkeypatch):
    from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
    from server.services import llm_factory, personal_context as pc
    from server.services.memory_migration import migrate_legacy_sync
    from server.services.memory_repository import repository
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)

    async def local(db):
        return True
    monkeypatch.setattr(llm_factory, "memory_models_are_local", local)
    async with repository() as repo:
        await repo.create(MemoryWrite(content="Lunch is at noon on weekdays", scope=MemoryScope(kind="global")),
                          MemoryActor(origin="user"))
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"]
    assert (await _row(execution_db, side)).no_memory is False
    ctx = await task_context.load(side, user_message="when is lunch?")
    assert (ctx.no_memory, ctx.no_learning, ctx.temporary) == (False, True, False)
    assert pc.may_show_memory(ctx) is True
    with pc.bind(ctx):
        block = await pc.assemble("lunch")
    assert block.receipt.memory_mode == "normal" and "Lunch is at noon on weekdays" in block.text
    # Its parent turning memory off turns it off here too, at the next turn.
    async with execution_db() as session:
        (await session.get(ConversationContext, PARENT)).no_memory = True
        await session.commit()
    assert (await task_context.load(side, user_message="and now?")).no_memory is True


async def test_it_writes_no_memory_and_no_lesson_even_were_its_row_to_allow_learning(execution_db, monkeypatch):
    """`no_learning` is on its row, and forced for any side chat in `effective_settings`: a row turned back on by
    hand still refuses every write."""
    from arslan.companion.memory import MemoryScope, MemoryWrite
    from server.db.companion_models import MemoryEntry
    from server.orchestrator.tool_caller import ToolCaller
    from server.services import lessons, memory_import, memory_tools_v2, personal_context as pc
    from server.services.memory_migration import migrate_legacy_sync
    from server.services.memory_repository import repository
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
    async with execution_db() as session:
        session.add(ConversationContext(id=PARENT, kind="chat", cloud_memory_allowed=True, allow_sensitive=True))
        await session.commit()
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"]
    async with execution_db() as session:
        (await session.get(ConversationContext, side)).no_learning = False
        await session.commit()
    ctx = await task_context.load(side, user_message="remember that lunch is at noon")
    assert ctx.no_learning is True
    learned = []

    async def record(*args, **kwargs):
        learned.append(args or kwargs)
    for name in ("record_applied", "capture"):
        monkeypatch.setattr(lessons, name, record)
    monkeypatch.setattr(lessons, "detours", lambda trace: [{"tool": "read_file"}])
    host = ToolCaller(actor="host", spawn_id=None, conversation_id=side)
    with pc.bind(ctx):
        assert (await memory_tools_v2.remember(
            {"action": "append", "kind": "preference", "content": "lunch is at noon"}, host))["code"] == \
            "learning_disabled"
        assert (await memory_tools_v2.note({"action": "add", "set": "about_you", "text": "lunch at noon"}, host))[
            "code"] == "learning_disabled"
        assert (await memory_import.propose({"why": "x"}, conversation_id=side, ask=None))["error"] == \
            "learning_disabled"
        with pytest.raises(MemoryError, match="learning_disabled"):
            async with repository() as repo:
                await repo.create(MemoryWrite(content="lunch is at noon", scope=MemoryScope(kind="global")),
                                  ctx.actor("extractor"))
        await lessons.after_turn(conversation_id=side, user_request="x", trace=[{"tool": "read_file"}],
                                 external_seen=False, recalled=[{"id": 1}], ok=True)
    assert learned == []
    async with execution_db() as session:
        assert await session.scalar(select(sa.func.count(MemoryEntry.id))) == 0


async def test_after_its_turn_nothing_is_noticed_and_it_is_never_compacted(execution_db, monkeypatch):
    """A long side chat drops its oldest parent messages first; a summary of its own would never be read."""
    from server.services import turn_facts
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"]
    for cid in (side, "c-control"):
        for n in range(8):
            await _say(execution_db, cid, "a long message " * 50, role="user" if n % 2 == 0 else "arslan",
                       minutes=10 + n)
    noticed = []

    async def capture(*args, **kwargs):
        noticed.append(args)
        return 0

    class Summarizer:
        async def chat(self, system, user, **kwargs):
            return LLMResponse(content="Goal: the side chat", usage={}, tool_calls=[])
    monkeypatch.setattr(turn_facts, "capture", capture)
    monkeypatch.setattr(memory, "_get_adapter", lambda conversation_id: Summarizer())
    turn = await task_context.load(side, user_message="and then?")
    await arslan._after_turn(side, "and then?", lambda e: None, turn, budget=200, reply_id=None, after=None)
    await memory.maybe_compact(side, budget=200)
    async with execution_db() as session:
        written = await session.scalar(select(ArslanSummary.id).where(ArslanSummary.conversation_id == side))
    assert noticed == [] and written is None
    await memory.maybe_compact("c-control", budget=200)         # the same messages in an ordinary conversation are
    async with execution_db() as session:
        assert await session.scalar(select(ArslanSummary.id).where(ArslanSummary.conversation_id == "c-control"))


async def test_a_side_chat_id_with_no_side_chats_row_runs_nothing(execution_db):
    """Nothing made it, so there is no parent to read: no turn, also when a route left a row of no kind."""
    with pytest.raises(MemoryError, match="side_chat_parent_missing"):
        await task_context.load(NO_ROW, user_message="hello")
    async with execution_db() as session:
        session.add(ConversationContext(id=NO_ROW))
        await session.commit()
    with pytest.raises(MemoryError, match="side_chat_parent_missing"):
        await task_context.load(NO_ROW, user_message="hello")
    assert phone_ids.kind_of(NO_ROW, None) == "side" and phone_ids.kind_of(NO_ROW, "side") == "side"
    assert not phone_ids.in_list(NO_ROW, None) and not phone_ids.in_list(NO_ROW, None, quick=True)


# -- its settings, model and pin are its parent's (card, rules 2 and 6) ---------------------------------------------

async def test_its_settings_model_and_pin_cannot_be_set(client):
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    async with client.db_maker() as session:
        session.add(ProviderConfig(label="ds", provider="deepseek", model="deepseek-chat", api_key="", is_primary=True))
        await session.commit()
        config = (await session.execute(select(ProviderConfig.id))).scalar_one()
    for got in (await client.put(f"/api/v1/conversations/{side}/context",
                                 json={"schema_version": 1, "expected_version": 1, "no_memory": True,
                                       "no_learning": True}),
                await client.put(f"/api/v1/conversations/{side}/model", json={"config_id": config, "model": "m"}),
                await client.delete(f"/api/v1/conversations/{side}/model")):
        assert got.status_code == 422 and got.json()["detail"]["code"] == "side_chat_inherits"
    for cid in (side, NO_ROW):
        assert (await client.put(f"/api/v1/conversations/{cid}/pin", json={"pinned": True})).status_code == 404
        assert (await client.put(f"/api/v1/conversations/{cid}/context", json={
            "schema_version": 1, "expected_version": 0, "no_learning": True})).status_code == 422
    assert await _row(client.db_maker, NO_ROW) is None


async def test_it_runs_on_its_parents_model(client):
    from server.services import llm_factory
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    async with client.db_maker() as session:
        session.add(ProviderConfig(label="ds", provider="deepseek", model="deepseek-chat", api_key="", is_primary=True))
        session.add(ProviderConfig(label="or", provider="openrouter", model="a/b", api_key=""))
        await session.commit()
        other = (await session.execute(select(ProviderConfig.id).where(ProviderConfig.label == "or"))).scalar_one()
    assert (await client.put(f"/api/v1/conversations/{PARENT}/model",
                             json={"config_id": other, "model": "a/c"})).status_code == 200
    got = (await client.get(f"/api/v1/conversations/{side}/model")).json()
    assert got["effective"] == {"config_id": other, "model": "a/c", "provider": "openrouter"}
    assert (await llm_factory.build_conversation_adapter(side)).model == "a/c"


async def test_its_project_is_its_parents_read_each_time(execution_db):
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"]
    async with execution_db() as session:
        session.add(Project(id="p1", name="P"))
        await session.commit()
        (await session.get(ConversationContext, PARENT)).project_id = "p1"            # moved into it after the branch
        await session.commit()
    assert (await task_context.load(side, user_message="hello")).project_id == "p1"
    assert (await _row(execution_db, side)).project_id is None          # never copied, so never in the project's list


# -- in no list, not on the phone (hole 2, `phone_ids.in_list`) -----------------------------------------------------

async def test_a_side_chat_is_in_no_list_and_not_on_the_phone(client):
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    await _say(client.db_maker, side, "a side needle", minutes=10)
    run = await _run(client.db_maker, side, False, minutes=10)
    parent_run = await _run(client.db_maker, PARENT, False)
    assert [c["conversation_id"] for c in (await client.get("/api/v1/conversations")).json()] == [PARENT]
    assert (await client.get("/api/v1/conversations/search", params={"q": "side needle"})).json() == []
    assert [c["id"] for c in (await client.get("/api/v1/phone/conversations")).json()["conversations"]] == [PARENT]
    assert (await client.get("/api/v1/phone/conversations", params={"kind": "quick"})).json()["conversations"] == []
    assert (await client.get("/api/v1/phone/live")).json()["conversation_ids"] == [PARENT]
    assert (await client.get(f"/api/v1/phone/conversations/{side}/history")).status_code == 404
    assert (await client.get(f"/api/v1/phone/runs/{run}/files")).status_code == 404
    assert (await client.post(f"/api/v1/phone/conversations/{side}/update", json={"kind": "chat"})).status_code == 404
    assert [r["id"] for r in (await client.get("/api/v1/runs")).json()] == [parent_run]       # the whole app's runs
    # What the parent's conversation_search tool reads: never a side chat, by its kind alone (its memory switch is on).
    from server.services import conversation_search
    assert (await _row(client.db_maker, side)).no_memory is False
    assert await conversation_search.search("side needle") == []
    assert await conversation_search.search("first question")       # the parent's own words are still found


async def test_the_whole_app_counts_its_work_as_its_parents(client):
    """The island, notifications and the waiting badge list it under its parent, which the window shows. Its turn
    stays an entry of its own on the island: the Stop for the parent's sub-sessions isn't what it runs."""
    from server.services import desktop_status
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    async with client.db_maker() as session:
        await sub_sessions.create_child(session, PARENT, "sub-kid")
        await session.commit()
        assert await sub_sessions.commanders(session, [side, PARENT, "c-other"]) == {side: PARENT}
    desktop_status._reset_for_tests()
    try:
        with desktop_status.working(side, title="what did it mean?"), \
                desktop_status.working("sub-kid", title="a sub-session's job", kind="job", job_id="job-a"):
            feed = (await client.get("/api/v1/island/feed")).json()
            assert sorted((a["conversation_id"], a["title"], a["job_id"]) for a in feed["active"]) == [
                (PARENT, "first question", f"{sub_sessions.STOP_ALL}{PARENT}"), (PARENT, "what did it mean?", None)]
            assert (await client.get("/api/v1/desktop/status")).json()["working"] == 1
    finally:
        desktop_status._reset_for_tests()


# -- it goes with its parent (card, rule 5) -------------------------------------------------------------------------

@pytest.mark.parametrize("choice", [None, "delete", "keep"])
async def test_deleting_the_parent_takes_its_side_chats_whatever_it_does_with_its_sub_sessions(client, choice):
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    await _say(client.db_maker, side, "a side question", minutes=10)
    if choice:
        async with client.db_maker() as session:
            await sub_sessions.create_child(session, PARENT, "sub-kid")
            await session.commit()
    got = await client.delete(f"/api/v1/conversations/{PARENT}" + (f"?sub_sessions={choice}" if choice else ""))
    assert got.status_code == 200, got.json()
    assert (await _row(client.db_maker, side)).kind == sub_sessions.DELETED
    async with client.db_maker() as session:
        assert await session.scalar(select(ArslanMessage.id).where(ArslanMessage.conversation_id == side)) is None
    sub_sessions._deleted.clear()                    # after a restart, the tombstone alone refuses it
    with pytest.raises(MemoryError, match="conversation_deleted"):
        await task_context.load(side, user_message="still there?")
    assert (await client.get(f"/api/v1/conversations/{PARENT}/side-chats")).status_code == 404


async def test_one_side_chat_is_deleted_only_when_named_as_one(client):
    ids = await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    await _say(client.db_maker, side, "a side question", minutes=10)
    assert (await client.delete(f"/api/v1/conversations/{side}")).status_code == 404   # the phone names none
    assert (await _row(client.db_maker, side)).kind == "side"
    assert (await client.delete(f"/api/v1/conversations/{side}?side_chat=true")).status_code == 200
    assert (await _row(client.db_maker, side)).kind == sub_sessions.DELETED
    async with client.db_maker() as session:
        kept = (await session.execute(select(ArslanMessage.id).where(ArslanMessage.conversation_id == PARENT)
                                      )).scalars().all()
    assert kept == ids and (await client.get(f"/api/v1/conversations/{PARENT}/side-chats")).json() == []
