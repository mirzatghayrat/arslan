"""S3b: undoing a turn takes back its conversation — the turn and every later one — and the facts those
turns taught, narrowly (card S3, S3b; ⓪Plan's answers in the S3b plan).

What it never does: wipe summaries, suppress a whole conversation, clear run prompts, tombstone a fact's
text (undo is not Forget), or touch an older fact a removed turn only re-confirmed (that turn's source goes).
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite
from server.db.models import (
    ArslanMessage, ArslanSummary, CompanionTask, ConversationEvent, MemoryDeletion, MemoryEntry, MemoryProposal,
    MemorySource, MemorySuppression, PermissionGrant, Run, TaskAttempt,
)
from server.orchestrator import arslan, memory
from server.registry import service as registry_service
from server.services import background_jobs, run_registry, turn_undo
from server.services.memory_repository import repository
from server.ws import arslan as ws_arslan

CID, OTHER = "undo-conversation", "undo-other"


async def _turn(maker, cid, text, reply="done", *, with_reply=True):
    mid = await memory.add_message(cid, "user", text)
    async with maker() as db:
        run = Run(conversation_id=cid, user_message=text, status="done", system_prompt="prompt of " + text)
        db.add(run)
        await db.flush()
        reply_id = None
        if with_reply:
            row = ArslanMessage(conversation_id=cid, role="arslan", content=reply, run_id=run.id)
            db.add(row)
            await db.flush()
            reply_id = row.id
        await db.commit()
        return SimpleNamespace(mid=mid, run=run.id, reply=reply_id)


async def _fact(content, turn, cid=CID):
    async with repository() as repo:
        made = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global")),
                                 MemoryActor(origin="user", source_message_id=turn.mid, source_run_id=turn.run,
                                             conversation_id=cid))
    return made["id"]


async def _messages(maker, cid):
    async with maker() as db:
        return [(r.role, r.content) for r in (await db.execute(
            select(ArslanMessage).where(ArslanMessage.conversation_id == cid).order_by(ArslanMessage.id))).scalars()]


async def _status(maker, entry_id):
    async with maker() as db:
        return (await db.get(MemoryEntry, entry_id)).status


async def test_undo_removes_the_turn_and_every_later_one_and_keeps_what_came_before(execution_db):
    await _turn(execution_db, OTHER, "other chat", "other reply")
    await _turn(execution_db, CID, "plan the garden", "tomatoes")
    second = await _turn(execution_db, CID, "add herbs", "basil")
    third = await _turn(execution_db, CID, "and flowers", "tulips")
    out = await turn_undo.undo(second.run)
    assert await _messages(execution_db, CID) == [("user", "plan the garden"), ("arslan", "tomatoes")]
    assert await _messages(execution_db, OTHER) == [("user", "other chat"), ("arslan", "other reply")]
    assert (out["messages"], out["later_turns"]) == (4, 1)
    assert await memory.add_message(CID, "user", "next") > third.reply      # no id handed out again (0069)


async def test_the_preview_says_what_the_undo_will_remove(execution_db):
    await _turn(execution_db, CID, "one")
    second = await _turn(execution_db, CID, "two")
    third = await _turn(execution_db, CID, "three")
    await _fact("Prefers tea.", second)
    await _fact("Lives by the sea.", third)
    shown = await turn_undo.preview(second.run)
    assert shown == {"conversation": True, "reason": None, "messages_after": 4, "later_turns": 1, "facts": 2}
    out = await turn_undo.undo(second.run)
    assert (out["messages"], out["later_turns"], out["facts"]) == (4, 1, 2)


async def test_the_facts_the_removed_turns_taught_go_and_nothing_else_does(execution_db):
    first = await _turn(execution_db, CID, "one")
    second = await _turn(execution_db, CID, "two")
    third = await _turn(execution_db, CID, "three")
    kept = await _fact("Works in Lisbon.", first)
    taught = await _fact("Prefers tea.", second)
    later = await _fact("Lives by the sea.", third)
    reconfirmed = await _fact("Has a cat.", first)
    async with repository() as repo:                  # a later run's own note (a job: its run, no message)
        by_run = (await repo.create(MemoryWrite(content="Keeps receipts in a folder.", scope=MemoryScope(kind="global")),
                                    MemoryActor(origin="host", source_run_id=third.run, conversation_id=CID)))["id"]
        pending = (await repo.create(MemoryWrite(content="Might like jazz.", scope=MemoryScope(kind="global")),
                                     MemoryActor(origin="extractor", source_message_id=third.mid,
                                                 conversation_id=CID)))["id"]
    async with execution_db() as db:                 # the second turn re-confirmed an older entry (Q4)
        entry = await db.get(MemoryEntry, reconfirmed)
        db.add(MemorySource(id=str(uuid.uuid4()), entry_id=reconfirmed, revision_id=entry.current_revision_id,
                            source_kind="conversation", source_ref={"message_id": second.mid, "run_id": second.run},
                            author="host", created_at=datetime.utcnow() + timedelta(seconds=1)))
        db.add(ArslanSummary(conversation_id=OTHER, summary="kept", up_to_message_id=1))
        await db.commit()
    await turn_undo.undo(second.run)
    assert [await _status(execution_db, e) for e in (kept, taught, later, reconfirmed, by_run, pending)] == [
        "active", "deleted", "deleted", "active", "deleted", "deleted"]
    async with execution_db() as db:
        proposal = await db.scalar(select(MemoryProposal).where(MemoryProposal.target_entry_id == pending))
        assert (proposal.status, proposal.reason) == ("dismissed", "turn_undone")
        refs = [s.source_ref for s in (await db.execute(
            select(MemorySource).where(MemorySource.entry_id == reconfirmed))).scalars()]
        assert refs == [{"message_id": first.mid, "run_id": first.run, "conversation_id": CID}]
        assert await db.scalar(select(func.count()).select_from(MemoryDeletion)) == 0      # not Forget
        assert await db.scalar(select(func.count()).select_from(ArslanSummary)) == 1       # no summary wipe
        assert (await db.get(Run, first.run)).system_prompt == "prompt of one"            # run prompts kept
        kinds = {(s.source_kind, s.source_id) for s in (await db.execute(select(MemorySuppression))).scalars()}
        assert kinds == {("message_id", str(second.mid)), ("message_id", str(third.mid)),
                         ("run_id", str(second.run)), ("run_id", str(third.run))}       # never the conversation


async def test_a_writer_from_an_undone_turn_cannot_save_its_fact_again(execution_db):
    await _turn(execution_db, CID, "one")
    second = await _turn(execution_db, CID, "two")
    await _fact("Prefers tea.", second)
    await turn_undo.undo(second.run)
    with pytest.raises(MemoryError, match="memory_source_deleted"):
        async with repository() as repo:
            await repo.create(MemoryWrite(content="Prefers tea.", scope=MemoryScope(kind="global")),
                              MemoryActor(origin="extractor", source_message_id=second.mid, conversation_id=CID))
    async with repository() as repo:                  # the same text from elsewhere is fine: undo is not Forget
        made = await repo.create(MemoryWrite(content="Prefers tea.", scope=MemoryScope(kind="global")),
                                 MemoryActor(origin="user", conversation_id=OTHER))
    assert made["status"] == "active"


async def _unfinished_task(maker, cid):
    async with maker() as db:
        db.add(CompanionTask(id="task-" + uuid.uuid4().hex, conversation_id=cid, attempt_id="a", budget={},
                             phase="waiting_user", created_at=datetime.utcnow() + timedelta(seconds=1)))
        await db.commit()


@pytest.mark.parametrize("busy", ["run", "turn_lock", "job", "task"])
async def test_refused_while_anything_in_the_conversation_is_still_going(execution_db, monkeypatch, busy):
    await _turn(execution_db, CID, "one")
    second = await _turn(execution_db, CID, "two")
    if busy == "run":
        monkeypatch.setattr(run_registry, "active_for", lambda cid: [999] if cid == CID else [])
    elif busy == "turn_lock":
        await ws_arslan._turn_lock(CID).acquire()
    elif busy == "job":
        monkeypatch.setattr(background_jobs, "jobs_for",
                            lambda cid: [SimpleNamespace(phase="running")] if cid == CID else [])
    else:
        await _unfinished_task(execution_db, CID)
    try:
        assert (await turn_undo.preview(second.run))["reason"] == "running"
        with pytest.raises(turn_undo.Refused) as refused:
            await turn_undo.undo(second.run)
        assert refused.value.code == "running"
        assert len(await _messages(execution_db, CID)) == 4
    finally:
        if busy == "turn_lock":
            ws_arslan._turn_lock(CID).release()


async def test_the_post_turn_job_gets_a_moment_then_the_undo_is_refused_and_a_retry_succeeds(execution_db, monkeypatch):
    monkeypatch.setattr(turn_undo, "FINISH_WAIT_S", 0.05)
    await _turn(execution_db, CID, "one")
    second = await _turn(execution_db, CID, "two")
    release = asyncio.Event()
    tail = asyncio.get_running_loop().create_task(release.wait())
    monkeypatch.setitem(arslan._after_turn_tail, CID, tail)
    with pytest.raises(turn_undo.Refused) as refused:
        await turn_undo.undo(second.run)
    assert refused.value.code == "finishing" and len(await _messages(execution_db, CID)) == 4
    release.set()
    await tail
    assert (await turn_undo.undo(second.run))["messages"] == 2


async def test_a_post_turn_job_that_ends_within_the_moment_is_waited_for(execution_db, monkeypatch):
    await _turn(execution_db, CID, "one")
    second = await _turn(execution_db, CID, "two")
    tail = asyncio.get_running_loop().create_task(asyncio.sleep(0.05))
    monkeypatch.setitem(arslan._after_turn_tail, CID, tail)
    assert (await turn_undo.undo(second.run))["messages"] == 2


async def test_refused_for_a_turn_already_folded_into_the_summary(execution_db):
    await _turn(execution_db, CID, "one")
    second = await _turn(execution_db, CID, "two")
    async with execution_db() as db:
        db.add(ArslanSummary(conversation_id=CID, summary="s", up_to_message_id=second.mid))
        await db.commit()
    assert (await turn_undo.preview(second.run))["reason"] == "summarised"
    with pytest.raises(turn_undo.Refused) as refused:
        await turn_undo.undo(second.run)
    assert refused.value.code == "summarised"


async def test_refused_for_a_turn_with_no_reply_and_for_a_second_undo(execution_db):
    await _turn(execution_db, CID, "one")
    card = await _turn(execution_db, CID, "a choice card answer", with_reply=False)
    with pytest.raises(turn_undo.Refused) as refused:
        await turn_undo.undo(card.run)
    assert refused.value.code == "none"
    second = await _turn(execution_db, CID, "two")
    await turn_undo.undo(second.run)
    with pytest.raises(turn_undo.Refused) as refused:
        await turn_undo.undo(second.run)
    assert refused.value.code == "already"
    assert (await turn_undo.preview(second.run))["reason"] == "already"


async def test_a_background_jobs_result_is_not_a_turn_of_its_own(execution_db):
    """A job's result arrives after later turns, so the last user message before it is not its turn's."""
    await _turn(execution_db, CID, "start a job")
    await _turn(execution_db, CID, "meanwhile")
    async with execution_db() as db:
        run = Run(conversation_id=CID, user_message="job", status="done")
        db.add(run)
        await db.flush()
        db.add(ArslanMessage(conversation_id=CID, role="arslan", content="job result", run_id=run.id, job_outcome="done"))
        await db.commit()
        job_run = run.id
    assert (await turn_undo.preview(job_run))["reason"] == "job"
    with pytest.raises(turn_undo.Refused) as refused:
        await turn_undo.undo(job_run)
    assert refused.value.code == "job" and len(await _messages(execution_db, CID)) == 5


async def test_the_recap_drops_only_the_removed_turns_memory_events(execution_db):
    await _turn(execution_db, CID, "one")
    before = datetime.utcnow() - timedelta(seconds=5)
    second = await _turn(execution_db, CID, "two")
    after = datetime.utcnow() + timedelta(seconds=5)
    async with execution_db() as db:
        for cid, kind, at in ((CID, "memory", before), (CID, "memory", after), (OTHER, "memory", after),
                              (CID, "distill", after)):
            db.add(ConversationEvent(conversation_id=cid, kind=kind, summary="s", created_at=at))
        await db.commit()
    await turn_undo.undo(second.run)
    async with execution_db() as db:
        left = {(e.conversation_id, e.kind, e.created_at) for e in (await db.execute(
            select(ConversationEvent).where(ConversationEvent.kind != "turn_undone"))).scalars()}
    assert left == {(CID, "memory", before), (OTHER, "memory", after), (CID, "distill", after)}


async def test_after_an_undo_no_expired_grant_comes_back_no_turn_grant_survives_and_conversation_grants_stay(
        execution_db):
    """⓪Plan's Q6: the turn clock (user turns so far) must never run backwards."""
    await _turn(execution_db, CID, "one")
    second = await _turn(execution_db, CID, "two")
    await _turn(execution_db, CID, "three")
    clock = await memory.user_turn_count(CID)
    expired = SimpleNamespace(ref_key="old_tools", grant="temporary", expires_turn=clock - 1)
    assert registry_service._active_toolset_keys([expired], clock) == []
    async with execution_db() as db:
        # the turn's own task starts just before its message is stored: found by its run, not its time
        db.add(CompanionTask(id="turn-two", conversation_id=CID, attempt_id="a", budget={}, phase="succeeded",
                             created_at=datetime.utcnow() - timedelta(hours=1)))
        db.add(CompanionTask(id="turn-three", conversation_id=CID, attempt_id="b", budget={}, phase="failed",
                             created_at=datetime.utcnow() + timedelta(seconds=1)))
        await db.flush()
        db.add(TaskAttempt(id="a", task_id="turn-two", number=1, spec_revision=1, status="succeeded",
                           run_ids=[second.run]))
        db.add(PermissionGrant(conversation_id=CID, task_id="turn-two", kind="command", target="x"))
        db.add(PermissionGrant(conversation_id=CID, task_id="turn-three", kind="command", target="z"))
        db.add(PermissionGrant(conversation_id=CID, task_id="", kind="command", target="y"))
        await db.commit()
    await turn_undo.undo(second.run)
    after = await memory.user_turn_count(CID)
    assert after == clock                                                # (i) the clock did not go back
    assert registry_service._active_toolset_keys([expired], after) == []
    await memory.add_message(CID, "user", "four")
    assert await memory.user_turn_count(CID) == clock + 1
    async with execution_db() as db:
        grants = {(g.task_id, g.target) for g in (await db.execute(select(PermissionGrant))).scalars()}
    assert grants == {("", "y")}                                         # (ii) gone, (iii) unchanged
