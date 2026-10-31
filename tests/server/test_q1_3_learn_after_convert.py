"""Q1 #3 (the user, 2026-10-29): a quick question turned into a chat learns like an ordinary conversation
from the moment it is turned, and its quick turns before that never teach.

Turning it clears `no_learning` and stores where learning starts
(`conversation_contexts.learns_after_message_id`, migration 0078). Clearing alone is not enough: the facts
extractor reads the user's recent messages, not only the latest one, so the first ordinary turn would learn
from the quick ones too. What this covers is the facts extractor; remember and memory_note in later turns may
still draw on the quick turns in the model's history (server/api/phone.py says what remains).
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from arslan.models import LLMResponse
from server.db.companion_models import ConversationContext, MemorySuppression
from server.db.migrations import runner
from server.db.migrations.versions import _0078_quick_learns_after as m0078
from server.db.models import ArslanMessage
from server.db.task_models import CompanionTask
from server.services import background_jobs
from server.ws import arslan as ws_arslan

Q = "phone-6b7c9a2e-1c1d-4f5e-9a8b-3c2d1e0f9a8b"


# -- migration 0078: add-only ------------------------------------------------------------------------------

def test_0078_adds_where_learning_starts_once_and_touches_nothing_else(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'contexts.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE conversation_contexts (id VARCHAR(100) PRIMARY KEY, "
                                 "no_learning BOOLEAN NOT NULL DEFAULT 0, kind VARCHAR(20))")
            conn.exec_driver_sql("INSERT INTO conversation_contexts (id, no_learning, kind) VALUES ('c-1', 1, 'quick')")
            m0078.upgrade_sync(conn)
            m0078.upgrade_sync(conn)
            columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversation_contexts)")]
            row = conn.exec_driver_sql("SELECT * FROM conversation_contexts").one()
    finally:
        engine.dispose()
    assert columns == ["id", "no_learning", "kind", "learns_after_message_id"]
    assert tuple(row) == ("c-1", 1, "quick", None)


def test_0078_leaves_a_database_without_the_table_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    try:
        with engine.begin() as conn:
            m0078.upgrade_sync(conn)
            assert conn.exec_driver_sql("SELECT name FROM sqlite_master").all() == []
    finally:
        engine.dispose()


def test_0078_runs_after_0071():
    order = [version for version, _ in runner.MIGRATIONS]
    assert order.index("0071") < order.index("0078")


# -- turning it ------------------------------------------------------------------------------------------

async def _row(client, conversation_id):
    async with client.db_maker() as db:
        return await db.get(ConversationContext, conversation_id)


async def _say(db_maker, conversation_id, text, role="user") -> int:
    async with db_maker() as db:
        message = ArslanMessage(conversation_id=conversation_id, role=role, content=text,
                                timestamp=datetime(2026, 10, 29, 8, 0, 0))
        db.add(message)
        await db.commit()
        return message.id


async def test_turning_a_quick_question_starts_its_learning_after_its_last_message(client):
    await client.post(f"/api/v1/phone/conversations/{Q}/quick")
    await _say(client.db_maker, Q, "I am vegetarian")
    last = await _say(client.db_maker, Q, "Noted: no meat.", role="arslan")
    got = await client.post(f"/api/v1/phone/conversations/{Q}/update", json={"kind": "chat"})
    assert got.status_code == 200
    row = await _row(client, Q)
    assert (row.kind, row.no_learning, row.learns_after_message_id) == ("chat", False, last)


async def test_a_retry_leaves_what_the_user_set_since(client):
    """A retry after a lost reply finds it already a chat: the user may have switched learning off in the
    window meanwhile, and the place learning starts stays where the turn put it."""
    await client.post(f"/api/v1/phone/conversations/{Q}/quick")
    last = await _say(client.db_maker, Q, "weather?")
    await client.post(f"/api/v1/phone/conversations/{Q}/update", json={"kind": "chat"})
    await _say(client.db_maker, Q, "and tomorrow?")
    async with client.db_maker() as db:
        (await db.get(ConversationContext, Q)).no_learning = True
        await db.commit()
    again = await client.post(f"/api/v1/phone/conversations/{Q}/update", json={"kind": "chat"})
    assert again.status_code == 200
    row = await _row(client, Q)
    assert (row.no_learning, row.learns_after_message_id) == (True, last)


# -- what the facts extractor reads -----------------------------------------------------------------------

async def _recent(monkeypatch, conversation_id, latest) -> str:
    """The user's recent messages as the facts extractor puts them before the model."""
    from server.services import turn_facts
    prompts = []

    class Model:
        async def chat(self, system, user, **kwargs):
            prompts.append(user)
            return LLMResponse(usage={}, content='{"facts": []}', tool_calls=[])

    async def adapter():
        return Model()
    monkeypatch.setattr(turn_facts, "_get_adapter", adapter)
    await turn_facts.extract(conversation_id, latest)
    return prompts[0].split("User's latest message:")[0]


@pytest.mark.parametrize("cid", [Q, "c-mac"], ids=["phone-made", "any-id"])
@pytest.mark.parametrize("turned", [True, False], ids=["turned", "ordinary"])
async def test_the_facts_extractor_reads_only_the_users_messages_after_the_turn(execution_db, monkeypatch, turned, cid):
    """Whatever the id looks like (#490 review, 6: the boundary is read for every conversation), and never Arslan's
    replies after it (4)."""
    await _say(execution_db, cid, "Noted: no meat.", role="arslan")
    last = await _say(execution_db, cid, "I am vegetarian")    # its quick turn's reply never came: the turn's last message
    await _say(execution_db, cid, "Here is a vegan plan for two.", role="arslan")
    await _say(execution_db, cid, "Plan dinner for two")
    async with execution_db() as db:
        db.add(ConversationContext(id=cid, kind="chat", learns_after_message_id=last if turned else None))
        await db.commit()
    recent = await _recent(monkeypatch, cid, "Plan dinner for two")
    assert "Plan dinner for two" in recent
    assert ("I am vegetarian" in recent) is not turned
    assert "vegan plan" not in recent


async def test_a_message_behind_a_forgotten_memory_is_never_read_after_the_turn(execution_db, monkeypatch):
    """#490 review, 2: after the turn the extractor reads the history as memory allows it
    (memory_history.eligible_messages): the source of a deleted memory entry never seeds memory again."""
    last = await _say(execution_db, Q, "weather?")
    forgotten = await _say(execution_db, Q, "I am vegan")
    await _say(execution_db, Q, "Plan dinner for two")
    async with execution_db() as db:
        db.add(ConversationContext(id=Q, kind="chat", learns_after_message_id=last))
        db.add(MemorySuppression(source_kind="message_id", source_id=str(forgotten), entry_id="deleted",
                                 cutoff_at=datetime(2026, 10, 29, 9, 0, 0)))
        await db.commit()
    recent = await _recent(monkeypatch, Q, "Plan dinner for two")
    assert "Plan dinner for two" in recent and "I am vegan" not in recent


# -- the next turn teaches ---------------------------------------------------------------------------------

# -- #490 review, 1: never while anything runs in the conversation ------------------------------------------------

@pytest.mark.parametrize("busy", ["turn", "job", "running", "verifying"])
async def test_turning_waits_while_anything_runs_in_the_conversation(client, monkeypatch, busy):
    """A chat turn holds the conversation's lock from before it loads the quick context and stores its message,
    and registers its run only later; a job or a task may run on after a turn. Turned meanwhile, the boundary
    would land below the running quick turn's own message, and that turn would read the kind as a chat."""
    await client.post(f"/api/v1/phone/conversations/{Q}/quick")
    await _say(client.db_maker, Q, "I am vegan")
    lock = ws_arslan._turn_lock(Q)
    if busy == "turn":
        await lock.acquire()
    elif busy == "job":
        monkeypatch.setattr(background_jobs, "jobs_for",
                            lambda cid: [SimpleNamespace(phase="running")] if cid == Q else [])
    else:
        async with client.db_maker() as db:
            db.add(CompanionTask(id="task-q", owner_id="local", conversation_id=Q, phase=busy, attempt_id="a",
                                 budget={}))
            await db.commit()
    try:
        got = await client.post(f"/api/v1/phone/conversations/{Q}/update", json={"kind": "chat"})
    finally:
        if lock.locked():
            lock.release()
        ws_arslan._turn_locks.pop(Q, None)
    assert got.status_code == 409 and got.json()["detail"] == "mac_busy"
    row = await _row(client, Q)
    assert (row.kind, row.no_learning, row.learns_after_message_id) == ("quick", True, None)


async def test_a_turn_that_arrives_while_it_is_turned_waits_and_runs_as_a_chat(client, monkeypatch):
    """#490 recheck: the lock is held while it is turned, so a turn that arrives then (the window's user_message
    takes the lock first) waits, and finds a chat."""
    await client.post(f"/api/v1/phone/conversations/{Q}/quick")
    await _say(client.db_maker, Q, "weather?")
    lock = ws_arslan._turn_lock(Q)
    seen = {}

    async def turn():
        async with lock:
            seen["kind"] = (await _row(client, Q)).kind
    real = background_jobs.jobs_for

    def jobs_for(conversation_id):                     # asked while it is turned: a turn arrives now
        if conversation_id == Q and "turn" not in seen:
            seen["locked"] = lock.locked()
            seen["turn"] = asyncio.get_running_loop().create_task(turn())
        return real(conversation_id)
    monkeypatch.setattr(background_jobs, "jobs_for", jobs_for)
    try:
        got = await client.post(f"/api/v1/phone/conversations/{Q}/update", json={"kind": "chat"})
        await seen["turn"]
    finally:
        ws_arslan._turn_locks.pop(Q, None)
    assert got.status_code == 200
    assert (seen["locked"], seen["kind"]) == (True, "chat")


@pytest.mark.parametrize("busy", ["turn", "job"])
async def test_the_window_cannot_change_a_conversations_switches_while_something_runs_in_it(client, monkeypatch, busy):
    """#490 recheck: the context PUT relied on turn_journal.active, which nothing sets. A turn holds the lock from
    before it loads the switches it runs with, and a job may run on after a turn."""
    lock = ws_arslan._turn_lock("c-mac")
    if busy == "turn":
        await lock.acquire()
    else:
        monkeypatch.setattr(background_jobs, "jobs_for",
                            lambda cid: [SimpleNamespace(phase="running")] if cid == "c-mac" else [])
    try:
        got = await client.put("/api/v1/conversations/c-mac/context", json={
            "expected_version": 0, "no_memory": True, "no_learning": True, "temporary": False,
            "cloud_memory_allowed": False, "allow_sensitive": False})
    finally:
        if lock.locked():
            lock.release()
        ws_arslan._turn_locks.pop("c-mac", None)
    assert got.status_code == 409 and got.json()["detail"]["code"] == "conversation_running"
    async with client.db_maker() as db:
        assert await db.get(ConversationContext, "c-mac") is None


@pytest.mark.parametrize("no_learning, status", [(False, 409), (True, 200)], ids=["switch-on", "keep-off"])
async def test_the_window_cannot_switch_learning_on_for_a_quick_question(client, no_learning, status):
    """#490 review, 5 (from #479): a quick question learns nothing until it is turned into a chat."""
    await client.post(f"/api/v1/phone/conversations/{Q}/quick")
    row = await _row(client, Q)
    got = await client.put(f"/api/v1/conversations/{Q}/context", json={
        "expected_version": row.version, "no_memory": False, "no_learning": no_learning, "temporary": False,
        "cloud_memory_allowed": False, "allow_sensitive": False})
    assert got.status_code == status, got.text
    if status == 409:
        assert got.json()["detail"]["code"] == "quick_question_learns_nothing"
    after = await _row(client, Q)
    assert (after.kind, after.no_learning) == ("quick", True)


@pytest.mark.parametrize("stored_row", [False, True], ids=["no-row", "row-without-kind"])
async def test_the_window_cannot_switch_learning_on_for_a_phone_conversation_with_no_kind(client, stored_row):
    """#490 follow-up (one rule, one reader, as on #486): one the phone made with no kind stored is read as a quick
    question (phone_ids.kind_of), so the window cannot switch its learning on either: every turn would read it as
    quick and learn nothing, while the switch said on."""
    await _say(client.db_maker, Q, "weather?")
    version = 0
    if stored_row:                                     # the window's PUT makes one without a kind (a project, say)
        async with client.db_maker() as db:
            db.add(ConversationContext(id=Q, no_memory=True))
            await db.commit()
        version = (await _row(client, Q)).version
    got = await client.put(f"/api/v1/conversations/{Q}/context", json={
        "expected_version": version, "no_memory": False, "no_learning": False, "temporary": False,
        "cloud_memory_allowed": False, "allow_sensitive": False})
    assert got.status_code == 409 and got.json()["detail"]["code"] == "quick_question_learns_nothing"
    row = await _row(client, Q)
    if stored_row:
        assert (row.kind, row.no_learning, row.version) == (None, False, 1)      # left as it was
    else:
        assert row is None


async def test_the_window_writes_a_conversations_switches_holding_its_lock(client, monkeypatch):
    """#490 recheck, follow-up: the context PUT holds the conversation's turn lock from its check until its write is
    committed, so a turn that arrives meanwhile waits and loads the switches as written."""
    from sqlalchemy.ext.asyncio import AsyncSession
    lock = ws_arslan._turn_lock("c-mac")
    seen = {"commits": []}
    real_commit = AsyncSession.commit

    async def commit(self):
        seen["commits"].append(lock.locked())
        return await real_commit(self)
    monkeypatch.setattr(AsyncSession, "commit", commit)

    async def turn():
        async with lock:
            row = await _row(client, "c-mac")
            seen["no_learning"] = row.no_learning if row else None
    real = background_jobs.jobs_for

    def jobs_for(conversation_id):                     # asked while the PUT checks: a turn arrives now
        if conversation_id == "c-mac" and "turn" not in seen:
            seen["locked"] = lock.locked()
            seen["turn"] = asyncio.get_running_loop().create_task(turn())
        return real(conversation_id)
    monkeypatch.setattr(background_jobs, "jobs_for", jobs_for)
    try:
        got = await client.put("/api/v1/conversations/c-mac/context", json={
            "expected_version": 0, "no_memory": False, "no_learning": True, "temporary": False,
            "cloud_memory_allowed": False, "allow_sensitive": False})
        await seen["turn"]
    finally:
        ws_arslan._turn_locks.pop("c-mac", None)
    assert got.status_code == 200, got.text
    assert seen["locked"] is True                      # held while it checks
    assert seen["commits"] and all(seen["commits"])    # and until its write is committed
    assert seen["no_learning"] is True                 # the waiting turn reads what was written


async def test_a_turned_quick_question_teaches_from_its_next_turn(execution_db, monkeypatch):
    """Q1a's own check, one step on: the same turn that taught nothing while the conversation was quick
    teaches once it is turned (lessons.after_turn reads the turn's memory context)."""
    from server.api import phone
    from server.orchestrator import arslan, tool_loop
    from server.services import lessons, personal_context, task_context
    from tests.server.test_q1a_quick_ask import _Model, _store, golden
    await _store(execution_db, Q, "quick")
    async with execution_db() as db:
        await phone.phone_update_conversation(Q, phone.ConversationUpdate(kind="chat"), db)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _Model([golden._Resp(content="done")]))
    golden._pin_workspace(monkeypatch)
    monkeypatch.setattr(lessons, "detours", lambda trace: [{"failed": "a", "worked": "b"}])

    async def candidates(found, user_request, conversation_id):
        return ["a practice"]
    taken = []

    async def capture(made, **kwargs):
        taken.append(made)
    monkeypatch.setattr(lessons, "detour_candidates", candidates)
    monkeypatch.setattr(lessons, "capture", capture)
    with personal_context.bind(await task_context.load(Q, user_message="weather?")):
        await arslan._handle_answer(Q, "weather?", lambda e: None, source="phone")
    await asyncio.gather(*list(lessons._background))
    assert taken
