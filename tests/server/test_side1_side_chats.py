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
- it is in no list of conversations and not on the phone, and it goes with its parent;
- deleted, it is still a side chat (#910 review): off the phone, out of the whole app's lists and off the island, also
  after a restart; a delete stops the turn in flight where it deletes, and no message is ever written into a deleted
  conversation, whatever the timing;
- its permission mode is its parent's (#910 review), read at each step, the narrowest up its chain, whatever its own
  row stores; one whose parent is out of reach or deleted runs in "Ask every step", never the default. A
  sub-session's mode reads as it did.
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
from server.services import background_jobs, permissions, phone_ids, settings_service, sub_sessions, task_context
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


# -- migration 0101 ----------------------------------------------------------------------------------------------

def test_0101_adds_the_branch_and_the_mark_once_and_leaves_a_database_without_the_table_alone(tmp_path):
    from server.db.migrations.versions import _0101_side_chats as m0101
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE conversation_contexts (id VARCHAR(100) PRIMARY KEY, version INTEGER)")
            conn.exec_driver_sql("INSERT INTO conversation_contexts (id, version) VALUES ('c-1', 3)")
            m0101.upgrade_sync(conn)
            m0101.upgrade_sync(conn)
            columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversation_contexts)")]
            row = conn.exec_driver_sql("SELECT * FROM conversation_contexts").one()
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE conversation_contexts")
            m0101.upgrade_sync(conn)
            assert conn.exec_driver_sql("SELECT name FROM sqlite_master").all() == []
    finally:
        engine.dispose()
    assert columns == ["id", "version", "branch_message_id", "outside_at_start"]
    assert tuple(row) == ("c-1", 3, None, None)


def test_0101_comes_after_0100_and_an_install_at_0100_gets_it_alone(tmp_path, monkeypatch):
    """0101 is the last migration, after 0100 (SUB7). An install whose ledger ends at 0100 gets it, and only it, at
    its next boot."""
    from server.db.migrations import runner
    from server.db.models import Base
    versions = [version for version, _ in runner.MIGRATIONS]
    assert versions[-2:] == ["0100", "0101"] and runner.head() == "0101"
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'arslan.db'}")
    try:
        Base.metadata.create_all(engine)
        with monkeypatch.context() as patched:
            patched.setattr(runner, "MIGRATIONS", runner.MIGRATIONS[:-1])
            with engine.begin() as conn:
                assert runner.apply_pending(conn)[-1] == "0100"
        with engine.begin() as conn:
            assert runner.apply_pending(conn) == ["0101"]
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


async def test_its_permission_mode_cannot_be_set(client):
    """S5a: a child conversation inherits its mode and never sets one; a side chat's is its parent's."""
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    for got in (await client.put(f"/api/v1/conversations/{side}/permission-mode", json={"mode": "plan"}),
                await client.post(f"/api/v1/conversations/{side}/permission-mode/start")):
        assert got.status_code == 422 and got.json()["detail"]["code"] == "side_chat_inherits"
    row = await _row(client.db_maker, side)
    assert row.permission_mode is None and row.previous_mode is None
    # The parent still sets its own.
    assert (await client.put(f"/api/v1/conversations/{PARENT}/permission-mode",
                             json={"mode": "plan"})).status_code == 200


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


# -- once deleted, still a side chat; a delete stops its turn (#910 review, round 1) ---------------------------------

#: How a side chat goes: alone (the window names it as one), or with its parent, whatever that delete does with the
#: parent's sub-sessions: the query each sends.
DELETES = {"alone": "?side_chat=true", "with-its-parent": "", "with-its-parent-and-sub-sessions": "?sub_sessions=delete",
           "with-its-parent-keeping-sub-sessions": "?sub_sessions=keep"}


async def _delete(client, side, how) -> None:
    if "sub-sessions" in how:
        async with client.db_maker() as session:
            await sub_sessions.create_child(session, PARENT, "sub-kid")
            await session.commit()
    got = await client.delete(f"/api/v1/conversations/{side if how == 'alone' else PARENT}{DELETES[how]}")
    assert got.status_code == 200, got.json()


@pytest.mark.parametrize("how", list(DELETES))
async def test_a_deleted_side_chat_stays_off_the_phone_and_out_of_the_whole_apps_lists_after_a_restart_too(client, how):
    """Its tombstone says `deleted`, not `side`, and its runs and tasks outlive it: its id still says what it was. So
    its run, the run's files and its history are not there for a phone, and the whole app's runs and tasks leave it
    out, whether this process still holds the delete's mark or not."""
    from server.services.task_repository import repository
    from tests.server.test_task_repository import spec
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    await _say(client.db_maker, side, "a side needle", minutes=10)
    run = await _run(client.db_maker, side, False, minutes=10)
    parent_run = await _run(client.db_maker, PARENT, False)
    async with repository() as repo:
        await repo.create(spec("t-side", instruction="a side needle"), side)
        await repo.create(spec("t-parent"), PARENT)
    phone = [f"/api/v1/phone/runs/{run}", f"/api/v1/phone/runs/{run}/files",
             f"/api/v1/phone/conversations/{side}/history"]
    await _delete(client, side, how)
    for restarted in (False, True):
        if restarted:
            sub_sessions._deleted.clear()            # a restart forgets this process's mark; the rows stay
        assert {path: (await client.get(path)).status_code for path in phone} == dict.fromkeys(phone, 404), restarted
        assert [r["id"] for r in (await client.get("/api/v1/runs")).json()] == [parent_run]
        assert [t["state"]["task_id"] for t in (await client.get("/api/v1/tasks")).json()] == ["t-parent"]
        assert side not in [c["conversation_id"] for c in (await client.get("/api/v1/conversations")).json()]
        assert (await client.get("/api/v1/conversations/search", params={"q": "side needle"})).json() == []
        assert side not in (await client.get("/api/v1/phone/live")).json()["conversation_ids"]
    assert phone_ids.kind_of(side, sub_sessions.DELETED) == "side"
    assert not phone_ids.in_list(side, sub_sessions.DELETED) and not phone_ids.in_list(side, "chat")


@pytest.mark.parametrize("how", ["alone", "with-its-parent"])
async def test_once_deleted_it_is_no_entry_of_its_own_on_the_island(client, how):
    """While it lives, its work and events are listed under its parent. Its tombstone names no parent and the window
    lists no side chat, so what this process still holds of it shows nowhere once it is deleted."""
    from server.services import desktop_status
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    desktop_status._reset_for_tests()
    try:
        with desktop_status.working(side, title="what did it mean?"):
            desktop_status.push("turn_finished", conversation_id=side, outcome="ok", title="what did it mean?",
                                work="turn")
            feed = (await client.get("/api/v1/island/feed")).json()
            assert [e["conversation_id"] for e in feed["events"]] == [PARENT]
            assert [a["conversation_id"] for a in feed["active"]] == [PARENT]
            await _delete(client, side, how)
            sub_sessions._deleted.clear()
            feed = (await client.get("/api/v1/island/feed")).json()
            status = (await client.get("/api/v1/desktop/status")).json()
        assert (feed["events"], feed["active"], status["events"]) == ([], [], [])
    finally:
        desktop_status._reset_for_tests()


async def _memory_on(execution_db) -> None:
    """What a full turn through `handle_user_message` reads, as the end-to-end test above sets it up."""
    from server.services.memory_activation import activate_sync
    from server.services.memory_migration import migrate_legacy_sync
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)


@pytest.mark.parametrize("turn_in, deleted, lands, task_cancel", [
    ("side", PARENT, "in-the-model-request", "done"), ("side", "side", "in-the-model-request", "done"),
    (PARENT, PARENT, "in-the-model-request", "done"), ("side", PARENT, "after-the-answer", "done"),
    ("side", PARENT, "in-the-model-request", "refused")],
    ids=["side-chat-its-parent-deleted", "side-chat-deleted-alone", "ordinary-conversation-deleted",
         "side-chat-its-parent-deleted-once-the-answer-is-back", "its-task-cancel-refused"])
async def test_a_delete_stops_the_turn_in_flight_and_nothing_is_written_there(execution_db, monkeypatch, turn_in,
                                                                              deleted, lands, task_cancel):
    """Codex's round-1 repro: the parent is deleted after the last model request's checkpoint and before its answer
    returns (or once it is back, before it is written), with no tool call after it. The delete comes in its own
    request, as the window's does, and stops the turn as the window's Stop would: the turn ends, its run is
    cancelled, and nothing is written where it ran. The delete returns once that run has ended, as it does for a
    job, though the model's stream takes a moment to close. An ordinary conversation's turn is stopped the same way,
    and a task cancel the repository refuses still stops the run itself."""
    from arslan.execution_checkpoint import save
    from server.api import conversations
    from server.orchestrator import promise_guard
    from server.services import run_registry, task_service
    from server.services.task_repository import TaskError
    if task_cancel == "refused":
        async def refuse(task_id, expected_version=None):
            raise TaskError("task_already_finished")
        monkeypatch.setattr(task_service, "cancel", refuse)
    await _memory_on(execution_db)
    ids = await _talk(execution_db)
    side = (await _start(execution_db, branch=ids[1]))["conversation_id"]
    cid, target = (side if turn_in == "side" else PARENT), (side if deleted == "side" else PARENT)
    there, never, answered = asyncio.Event(), asyncio.Event(), []

    async def held():
        there.set()
        try:
            await never.wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.5)            # a provider's stream closing
            raise

    class Adapter:
        async def chat(self, system, user, **kwargs):
            await save("before_model")          # as every provider does first
            if lands == "in-the-model-request":
                await held()
            answered.append(True)
            return LLMResponse(content="It meant the first one.", usage={}, tool_calls=[])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())

    async def correct(full_text, conversation_id=None):     # awaited between the answer and its write
        await held()
    if lands == "after-the-answer":
        monkeypatch.setattr(promise_guard, "correct", correct)
    turn = asyncio.create_task(arslan.handle_user_message(cid, "what did that mean?", lambda event: None))
    try:
        waiting = asyncio.ensure_future(there.wait())
        await asyncio.wait({waiting, turn}, return_when=asyncio.FIRST_COMPLETED, timeout=10)
        waiting.cancel()
        assert there.is_set(), turn
        [run_task] = [run_registry.get(run_id) for run_id in run_registry.active_for(cid)]
        async with execution_db() as session:
            await conversations.delete_conversation(target, sub_sessions=None, sub_session=False,
                                                    side_chat=deleted == "side", db=session)
        assert run_task.done(), "the delete returned while the run it stopped was still ending"
        await asyncio.wait({turn}, timeout=5)
        assert turn.done(), "the delete left the turn running"
    finally:
        never.set()
        await asyncio.wait({turn}, timeout=5)
    assert turn.result() is None                # stopped, as the window's Stop ends a turn
    async with execution_db() as session:
        said = (await session.execute(select(ArslanMessage.conversation_id).where(
            ArslanMessage.conversation_id.in_((side, PARENT))))).scalars().all()
        run = (await session.execute(select(Run).where(Run.conversation_id == cid))).scalar_one()
    assert said == ([PARENT] * len(ids) if deleted == "side" else [])
    assert run.status == "cancelled" and answered == ([True] if lands == "after-the-answer" else [])


@pytest.mark.parametrize("turn_in", ["side", PARENT], ids=["side-chat", "ordinary-conversation"])
async def test_a_delete_committed_as_the_reply_is_inserted_leaves_no_message(execution_db, monkeypatch, tmp_path,
                                                                             turn_in):
    """The interleaving no stop can catch: the model has answered and the delete commits, from another connection,
    after the turn's last await and before its INSERT runs (the hook runs right before SQLite executes it). A check
    and a separate insert would both pass and write; the insert reads the tombstone itself, writes nothing, and the
    turn ends saying why."""
    import sqlite3
    await _memory_on(execution_db)
    ids = await _talk(execution_db)
    side = (await _start(execution_db, branch=ids[1]))["conversation_id"]
    cid, gone = (side if turn_in == "side" else PARENT), (PARENT, side)

    class Adapter:
        async def chat(self, system, user, **kwargs):
            return LLMResponse(content="It meant the first one.", usage={}, tool_calls=[])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    reached = []

    def delete_meanwhile(conn, cursor, statement, parameters, context, executemany):
        values = [value for row in (parameters if executemany else [parameters])
                  for value in (row.values() if isinstance(row, dict) else row)]
        if reached or not statement.lstrip().startswith("INSERT INTO arslan_messages") or "arslan" not in values \
                or cid not in values:
            return
        reached.append(statement)
        other = sqlite3.connect(tmp_path / "execution.db")
        try:                                    # the delete's own transaction: its rows go, its tombstone is written
            marks = ", ".join("?" for _ in gone)
            other.execute(f"DELETE FROM arslan_messages WHERE conversation_id IN ({marks})", gone)
            other.execute(f"UPDATE conversation_contexts SET kind = 'deleted', parent_id = NULL WHERE id IN ({marks})",
                          gone)
            other.commit()
        finally:
            other.close()
    engine = execution_db.kw["bind"].sync_engine
    sa.event.listen(engine, "before_cursor_execute", delete_meanwhile)
    refused = None
    try:
        await arslan.handle_user_message(cid, "what did that mean?", lambda event: None)
    except MemoryError as error:
        refused = error.code
    finally:
        sa.event.remove(engine, "before_cursor_execute", delete_meanwhile)
    async with execution_db() as session:
        said = (await session.execute(select(ArslanMessage.content).where(
            ArslanMessage.conversation_id.in_(gone)))).scalars().all()
    assert (len(reached), said, refused) == (1, [], "conversation_deleted")


@pytest.mark.parametrize("kind", ["side", "sub", "chat", "no-row"])
async def test_no_message_is_written_into_a_deleted_conversation_whatever_it_was(execution_db, kind):
    """The one write every message goes through: a reply, a choice card, a message typed during a turn, a job's
    result (a sub-session's reply is one), a restart's note. Its tombstone alone refuses it: no mark of this process."""
    from server.orchestrator.memory import add_message
    await _talk(execution_db)
    cid = (await _start(execution_db))["conversation_id"] if kind == "side" else {
        "sub": "sub-kid", "chat": "c-chat", "no-row": "c-never-seen"}[kind]
    async with execution_db() as session:
        if kind == "sub":
            await sub_sessions.create_child(session, PARENT, cid)
        elif kind == "chat":
            session.add(ConversationContext(id=cid, kind="chat"))
        await session.commit()
    written = await add_message(cid, "arslan", "before the delete", job_outcome="done")
    async with execution_db() as session:
        row = await session.get(ArslanMessage, written)
    assert (row.conversation_id, row.content, row.job_outcome) == (cid, "before the delete", "done")
    assert abs(row.timestamp - datetime.utcnow()) < timedelta(minutes=1)      # stamped as the ORM's default did
    async with execution_db() as session:              # what DELETE /conversations/{id} commits
        await session.execute(sa.delete(ArslanMessage).where(ArslanMessage.conversation_id == cid))
        await sub_sessions.tombstone(session, [cid])
        await session.commit()
    with pytest.raises(MemoryError, match="conversation_deleted"):
        await add_message(cid, "arslan", "after the delete")
    async with execution_db() as session:
        assert await session.scalar(select(ArslanMessage.id).where(ArslanMessage.conversation_id == cid)) is None


async def test_a_restart_tells_no_deleted_conversation_of_its_cut_job_and_still_tells_the_next(execution_db,
                                                                                               monkeypatch):
    """A job that outlived its conversation's delete (it waits STOP_WAIT_S), then the process: at boot its note is
    refused as any write into a tombstone is, and the conversation after it is still told."""
    from unittest.mock import AsyncMock
    from server.services import runtime_messages
    from server.services.task_repository import repository
    from tests.server.test_task_repository import spec
    monkeypatch.setattr(runtime_messages, "selected_locale", AsyncMock(return_value="en"))
    async with repository() as repo:
        for identity, cid in (("job-gone", "c-gone"), ("job-kept", "c-kept")):
            created = await repo.create(spec(identity, instruction=f"Goal of {identity}"), cid,
                                        privacy={"driver": {"kind": "background"}})
            await repo.start(identity, created["version"])
    async with execution_db() as session:
        await sub_sessions.tombstone(session, ["c-gone"])
        await session.commit()
    async with repository() as repo:
        assert await repo.recover_interrupted() == 2
    assert await background_jobs.report_interrupted() == 2
    async with execution_db() as session:
        assert (await session.execute(select(ArslanMessage.conversation_id))).scalars().all() == ["c-kept"]


# -- its permission mode is its parent's, the narrowest up its chain (#910 review, round 1) --------------------------

async def _own_mode(db, cid, mode) -> None:
    """A mode on this conversation's own row, written straight to the database."""
    async with db() as session:
        row = await session.get(ConversationContext, cid) or ConversationContext(id=cid)
        row.permission_mode = mode
        session.add(row)
        await session.commit()


async def _default_mode(db, mode) -> None:
    async with db() as session:
        await settings_service.update_settings(session, {"default_permission_mode": mode})


@pytest.mark.parametrize("mode", permissions.MODES)
async def test_its_mode_is_its_parents_for_every_reader_and_follows_it_at_the_next_step(client, mode):
    """Codex's round-1 repro: its parent set to plan through the window's route, and it read the default (ask_risky).
    It runs in whatever its parent chose, for every reader of a conversation's mode: `mode_for` (the cards and full
    access's answers, the ledger, the status, the phone's details), the window's route, plan's refusal, and the note
    a scheduled run's refused command gets (ASK1-b). The default is never the parent's choice here, so reading it
    would show. Read at each step, never copied: when its parent tightens, or from plan presses Start, so does it."""
    from server.orchestrator import command_gate
    permissions._reset_for_tests()
    await _default_mode(client.db_maker, "plan" if mode == "full_access" else "full_access")
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    url = f"/api/v1/conversations/{PARENT}/permission-mode"

    async def agreed() -> str:
        state = await permissions.mode_for(side)
        assert state == await permissions.mode_for(PARENT), (mode, state)
        got = (await client.get(f"/api/v1/conversations/{side}/permission-mode")).json()
        assert (got["own"], got["chosen"], got["mode"]) == (None, state.chosen, state.mode)
        refused = await permissions.plan_refusal("write_file", {"path": "a.txt", "content": "x"}, side)
        assert (refused is not None) is (state.chosen == "plan")
        assert await command_gate._chose_ask_every_step(side) is (state.chosen == "ask")
        return state.chosen
    assert (await client.put(url, json={"mode": mode})).status_code == 200
    assert await agreed() == mode
    later = await client.post(f"{url}/start") if mode == "plan" else await client.put(url, json={"mode": "plan"})
    assert later.status_code == 200
    assert await agreed() == ("full_access" if mode == "plan" else "plan")


@pytest.mark.parametrize("between, top, expected", [
    ("full_access", "plan", "plan"), ("ask_risky", "ask", "ask"), ("ask", "full_access", "ask"),
    (None, "plan", "plan"), ("plan", None, "plan")],
    ids=["its-parent-wider-the-top-in-plan", "its-parent-wider-the-top-asking", "its-parent-narrower",
         "its-parent-unset", "the-top-unset"])
async def test_up_a_longer_chain_the_narrowest_mode_applies(execution_db, between, top, expected):
    """Its parent in a wider mode while an ancestor is narrower, and the other way round: the narrowest along the
    chain (`permissions.narrower`, as for a sub-session), which the sub-session between reads too. Nothing makes this
    chain (a side chat's parent is an ordinary conversation, `side_chats.create`); written here as Codex's P04 wrote
    it, it is read through `sub_sessions._chain`, as any chain is. The default is full access."""
    await _default_mode(execution_db, "full_access")
    await _talk(execution_db)
    side = (await _start(execution_db))["conversation_id"]
    async with execution_db() as session:
        await sub_sessions.create_child(session, PARENT, "sub-mid")
        (await session.get(ConversationContext, side)).parent_id = "sub-mid"
        await session.commit()
    await _own_mode(execution_db, PARENT, top)
    await _own_mode(execution_db, "sub-mid", between)
    assert [(await permissions.mode_for(cid)).chosen for cid in (side, "sub-mid")] == [expected, expected]


#: How a side chat's parent is out of its reach: no row for its id, or one of no kind (as a route could leave); its
#: parent's row gone, or the parent's row of a sub-session between them (a chain nothing makes, as above), the one
#: between unset or in plan (a mode it could read still narrows); deleted with its parent through the route, after a
#: restart too; its parent's tombstone alone; or a delete under way (this process's mark, before its commit).
OUT_OF_REACH = [("no-row", "ask"), ("a-row-of-no-kind", "ask"), ("its-parents-row-gone", "ask"),
                ("a-sub-session-between-whose-parent-is-gone", "ask"),
                ("a-sub-session-between-in-plan-whose-parent-is-gone", "plan"),
                ("deleted-with-its-parent", "ask"), ("its-parents-tombstone-alone", "ask"),
                ("a-delete-under-way", "ask")]


@pytest.mark.parametrize("how, expected", OUT_OF_REACH, ids=[how for how, _ in OUT_OF_REACH])
async def test_one_whose_parent_is_out_of_reach_or_deleted_runs_in_ask_never_the_default(client, how, expected):
    """Fails closed, as an unreadable mode does: "Ask every step", or narrower where it read a narrower mode; never
    the default and never its parent's last (both full access here). Known by its id as well as its row
    (`phone_ids.kind_of`): a deleted side chat's row says `deleted`, and a side chat's id with no row is still one."""
    await _default_mode(client.db_maker, "full_access")
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    await _own_mode(client.db_maker, PARENT, "full_access")
    cid = NO_ROW if how in ("no-row", "a-row-of-no-kind") else side
    async with client.db_maker() as session:
        if how == "a-row-of-no-kind":
            session.add(ConversationContext(id=NO_ROW))
        elif how.startswith("a-sub-session-between"):
            mid = await sub_sessions.create_child(session, PARENT, "sub-mid")
            mid.permission_mode = "plan" if "in-plan" in how else None
            (await session.get(ConversationContext, side)).parent_id = "sub-mid"
        elif how == "its-parents-tombstone-alone":
            await sub_sessions.tombstone(session, [PARENT])
        await session.commit()
        if how == "its-parents-row-gone" or how.startswith("a-sub-session-between"):
            await session.execute(sa.delete(ConversationContext).where(ConversationContext.id == PARENT))
            await session.commit()
    if how == "deleted-with-its-parent":
        assert (await client.delete(f"/api/v1/conversations/{PARENT}")).status_code == 200
    elif how == "a-delete-under-way":
        sub_sessions._deleted.update([PARENT, side])
    for restarted in (False, True) if how == "deleted-with-its-parent" else (False,):
        if restarted:
            sub_sessions._deleted.clear()            # a restart forgets this process's mark; the tombstones stay
        assert (await permissions.mode_for(cid)).chosen == expected, (how, restarted)
        got = (await client.get(f"/api/v1/conversations/{cid}/permission-mode")).json()
        assert (got["own"], got["chosen"], got["mode"]) == (None, expected, expected)


@pytest.mark.parametrize("stored, parent, expected", [
    ("full_access", "plan", "plan"), ("plan", "full_access", "full_access"), ("not-a-mode", "ask_risky", "ask_risky")],
    ids=["wider-than-its-parent", "narrower-than-its-parent", "not-a-mode"])
async def test_a_mode_an_older_row_stores_for_it_is_never_read(client, stored, parent, expected):
    """No route sets one (`side_chat_inherits`). One an older row holds, written straight to the database here, is
    not read at all: not as the top of its chain, which would widen it past its parent; not as a narrowing, since its
    mode is its parent's, exactly; not as a stored value that reads "ask". The window's route says it has none of its
    own and nothing for plan's Start to go back to."""
    await _talk(client.db_maker)
    side = (await _start(client.db_maker))["conversation_id"]
    async with client.db_maker() as session:
        row = await session.get(ConversationContext, side)
        row.permission_mode, row.previous_mode = stored, "full_access"
        await session.commit()
    assert (await client.put(f"/api/v1/conversations/{PARENT}/permission-mode",
                             json={"mode": parent})).status_code == 200
    assert (await permissions.mode_for(side)).chosen == expected
    got = (await client.get(f"/api/v1/conversations/{side}/permission-mode")).json()
    assert (got["own"], got["previous"], got["chosen"]) == (None, None, expected)


#: Sub-session chains as `create_child` makes them (two and three rows, a stored value that isn't a mode), and ones
#: that can't be read (a parent's row gone, none named, a loop, a deleted parent), each row's mode such that reading
#: the wrong row as the top would show: id: (kind, parent_id, permission_mode).
_SUB_CHAINS = {
    "c-top": ("chat", None, "ask_risky"), "sub-a": ("sub", "c-top", "full_access"), "sub-b": ("sub", "sub-a", None),
    "c-bare": (None, None, None), "sub-c": ("sub", "c-bare", "ask"), "sub-junk": ("sub", "c-top", "FULL"),
    "sub-orphan": ("sub", "c-gone", "full_access"), "sub-unnamed": ("sub", None, None),
    "sub-loop-1": ("sub", "sub-loop-2", "full_access"), "sub-loop-2": ("sub", "sub-loop-1", "ask_risky"),
    "c-dead": ("deleted", None, "plan"), "sub-dead": ("sub", "c-dead", "full_access")}


def _as_before(default: str, cid: str) -> str:
    """`permissions._chosen` as it read before #910's round-1 fix, over `_SUB_CHAINS`: the reference here."""
    chain, seen, current = [], set(), cid
    while current and current not in seen and len(seen) < 16:
        seen.add(current)
        if current not in _SUB_CHAINS:
            break
        kind, parent, own = _SUB_CHAINS[current]
        chain.append(None if own is None else own if own in permissions.MODES else "ask")
        current = parent if kind == "sub" else None
    mode = (chain[-1] if chain else None) or default
    for own in reversed(chain[:-1]):
        if own is not None:
            mode = permissions.narrower(own, mode)
    return mode


@pytest.mark.parametrize("default", ["full_access", "plan"])
async def test_a_sub_sessions_mode_reads_as_it_did(execution_db, default):
    """The guard: walking side chats through `sub_sessions._chain` changes no sub-session's mode. On every chain
    here, and for ids with no row, the resolver reads what the walk before it read (`_as_before`), whatever one makes
    of each answer: how a sub-session's chain that can't be read should read is S5a's and SUB's, not this fix's."""
    await _default_mode(execution_db, default)
    async with execution_db() as session:
        for cid, (kind, parent, own) in _SUB_CHAINS.items():
            session.add(ConversationContext(id=cid, kind=kind, parent_id=parent, permission_mode=own))
        await session.commit()
    for cid in (*_SUB_CHAINS, "sub-no-row", "c-no-row"):
        assert (await permissions.mode_for(cid)).chosen == _as_before(default, cid), cid
