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
from tests.server.test_promise_guard import maker  # noqa: F401 — a chat database for handle_user_message

CID, OTHER = "undo-conversation", "undo-other"


async def _turn(sessions, cid, text, reply="done", *, with_reply=True):
    mid = await memory.add_message(cid, "user", text)
    async with sessions() as db:
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


async def _messages(sessions, cid):
    async with sessions() as db:
        return [(r.role, r.content) for r in (await db.execute(
            select(ArslanMessage).where(ArslanMessage.conversation_id == cid).order_by(ArslanMessage.id))).scalars()]


async def _status(sessions, entry_id):
    async with sessions() as db:
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
    assert shown == {"conversation": True, "reason": None, "messages_after": 4, "later_turns": 1, "facts": 2,
                     "last_message_id": third.reply}
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
                            source_kind="conversation",
                            source_ref={"message_id": second.mid, "run_id": second.run, "conversation_id": CID},
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


async def _unfinished_task(sessions, cid):
    async with sessions() as db:
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


# ── ⓪Plan's review of #329: the reviewer's probes, now asserting the fixed behaviour ─────────────────

A, B = "probe-a", "probe-b"


async def _plain(sessions, cid, text, reply="done"):
    mid = await memory.add_message(cid, "user", text)
    async with sessions() as db:
        run = Run(conversation_id=cid, user_message=text, status="done")
        db.add(run)
        await db.flush()
        row = ArslanMessage(conversation_id=cid, role="arslan", content=reply + " " + text, run_id=run.id)
        db.add(row)
        await db.flush()
        await db.commit()
        return SimpleNamespace(mid=mid, run=run.id, reply=row.id)


async def _reply_only(sessions, cid, text):
    """A reply with a run and no user message of its own: a scheduled fire bound to the conversation
    (scheduler.run_arslan_turn) or a resumed task (task_service.resume_turn)."""
    async with sessions() as db:
        run = Run(conversation_id=cid, user_message=text, status="done")
        db.add(run)
        await db.flush()
        db.add(ArslanMessage(conversation_id=cid, role="arslan", content=text, run_id=run.id))
        await db.commit()
        return run.id


async def test_probe_1_the_clock_never_runs_backwards_across_two_undos(execution_db):
    ts = [await _plain(execution_db, A, f"t{i}") for i in range(1, 6)]
    await turn_undo.undo(ts[4].run)
    assert await memory.user_turn_count(A) == 5
    await _plain(execution_db, A, "t6")
    out = await turn_undo.undo(ts[2].run)
    assert out["later_turns"] == 2 and await memory.user_turn_count(A) == 6
    await _plain(execution_db, A, "t7")
    assert await memory.user_turn_count(A) == 7 and await memory.user_turn_count(B) == 0


async def test_probe_2_a_fact_the_user_accepted_on_the_memory_page_stays(execution_db):
    """🟠3: a fact goes only when every source is from the undone turns; the user's acceptance is not."""
    await _plain(execution_db, A, "one")
    second = await _plain(execution_db, A, "I have a cat")
    async with repository() as repo:
        made = await repo.create(MemoryWrite(content="Has a cat.", scope=MemoryScope(kind="global")),
                                 MemoryActor(origin="extractor", source_message_id=second.mid,
                                             source_run_id=second.run, conversation_id=A))
    async with execution_db() as db:
        proposal = await db.scalar(select(MemoryProposal).where(MemoryProposal.target_entry_id == made["id"]))
    async with repository() as repo:
        await repo.resolve_proposal(proposal.id, accept=True, actor=MemoryActor(origin="user"))
    assert (await turn_undo.preview(second.run))["facts"] == 0
    await turn_undo.undo(second.run)
    assert await _status(execution_db, made["id"]) == "active"
    async with execution_db() as db:
        refs = [s.source_ref for s in (await db.execute(
            select(MemorySource).where(MemorySource.entry_id == made["id"]))).scalars()]
    assert refs and not any(r.get("message_id") == second.mid for r in refs)     # only the turn's source went


async def test_probe_3_a_fact_another_conversation_saved_explicitly_stays(execution_db):
    import hashlib
    from arslan.companion.content_policy import normalized_memory
    await _plain(execution_db, A, "one")
    second = await _plain(execution_db, A, "my cat is called Miso")
    content = "The user's cat is called Miso."
    async with repository() as repo:
        made = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global")),
                                 MemoryActor(origin="extractor", source_message_id=second.mid,
                                             source_run_id=second.run, conversation_id=A))
    b1 = await _plain(execution_db, B, "remember: my cat is called Miso")
    digest = hashlib.sha256(normalized_memory(content).encode()).hexdigest()
    async with repository() as repo:
        saved = await repo.create(MemoryWrite(content=content, scope=MemoryScope(kind="global")),
                                  MemoryActor(origin="host", source_message_id=b1.mid, source_run_id=b1.run,
                                              conversation_id=B, explicit_save_ref=f"message:{b1.mid}",
                                              explicit_save_digest=digest, allow_global_save=True))
    assert saved["id"] == made["id"]
    await turn_undo.undo(second.run)
    assert await _status(execution_db, made["id"]) == "active"


async def test_probe_4_a_source_from_another_conversation_with_the_same_message_id_is_not_touched(execution_db):
    """🟡6: turn_entries is fenced by conversation."""
    await _plain(execution_db, A, "one")
    next_id = (await _plain(execution_db, A, "two")).reply + 1
    async with repository() as repo:
        old = await repo.create(MemoryWrite(content="Works in Lisbon.", scope=MemoryScope(kind="global")),
                                MemoryActor(origin="user", source_message_id=next_id, conversation_id="deleted-c"))
    third = await _plain(execution_db, A, "three")
    assert third.mid == next_id
    await turn_undo.undo(third.run)
    assert await _status(execution_db, old["id"]) == "active"


@pytest.mark.parametrize("case", ["scheduled fire", "resumed task"])
async def test_probes_5_and_9_a_reply_that_is_not_the_answer_to_the_last_message_is_refused(execution_db, case):
    """🟠2: a scheduled fire's or a resumed task's reply has no user message of its own; undoing it took the
    turn before it."""
    if case == "resumed task":
        await memory.add_message(A, "user", "build the report")        # the turn that paused, no reply
    await _plain(execution_db, A, "unrelated question", "unrelated answer")
    run = await _reply_only(execution_db, A, "today's digest" if case == "scheduled fire" else "report done")
    before = await _messages(execution_db, A)
    assert (await turn_undo.preview(run))["reason"] == "not_own_turn"
    with pytest.raises(turn_undo.Refused) as refused:
        await turn_undo.undo(run)
    assert refused.value.code == "not_own_turn" and await _messages(execution_db, A) == before


async def test_probe_6_interleaved_conversations_are_fenced(execution_db):
    a1 = await _plain(execution_db, A, "a1")
    await _plain(execution_db, B, "b1")
    await _plain(execution_db, A, "a2")
    b2 = await _plain(execution_db, B, "b2")
    async with repository() as repo:
        fb = await repo.create(MemoryWrite(content="Likes jazz.", scope=MemoryScope(kind="global")),
                               MemoryActor(origin="user", source_message_id=b2.mid, source_run_id=b2.run,
                                           conversation_id=B))
    clock_b = await memory.user_turn_count(B)
    await turn_undo.undo(a1.run)
    assert await _messages(execution_db, A) == [] and len(await _messages(execution_db, B)) == 4
    assert await _status(execution_db, fb["id"]) == "active"
    assert await memory.user_turn_count(B) == clock_b and await memory.user_turn_count(A) == 2


async def test_probe_7_a_turn_that_arrived_after_the_box_opened_refuses_the_undo(execution_db):
    """🟠1: the undo is held to the range the box showed."""
    await _plain(execution_db, A, "one")
    second = await _plain(execution_db, A, "two")
    shown = await turn_undo.preview(second.run)
    assert (shown["messages_after"], shown["later_turns"], shown["last_message_id"]) == (2, 0, second.reply)
    await _plain(execution_db, A, "sent from the phone meanwhile")
    with pytest.raises(turn_undo.Refused) as refused:
        await turn_undo.undo(second.run, last=shown["last_message_id"])
    assert refused.value.code == "changed" and len(await _messages(execution_db, A)) == 6
    again = await turn_undo.preview(second.run)
    assert (await turn_undo.undo(second.run, last=again["last_message_id"]))["messages"] == 4


async def test_probe_8_a_message_in_another_conversation_between_question_and_answer_is_not_touched(execution_db):
    await _plain(execution_db, A, "earlier")
    await memory.add_message(A, "user", "question in A")
    await memory.add_message(B, "user", "question in B")
    run_a = await _reply_only(execution_db, A, "answer in A")
    await turn_undo.undo(run_a)
    assert await _messages(execution_db, A) == [("user", "earlier"), ("arslan", "done earlier")]
    assert await _messages(execution_db, B) == [("user", "question in B")]


async def test_a_choice_card_turn_that_streamed_text_is_a_turn_and_can_be_undone(maker, monkeypatch):  # noqa: F811
    """🟡12: since K8a, text that went out before a choice card is stored as the turn's reply, with its run:
    that turn is undoable like any other (intended: it is a turn)."""
    from server.orchestrator import tool_loop
    from server.db import session as db_session
    text = "Here is what I found so far about the three options and how they compare. " * 3
    clarify = {"question": "Which one?", "options": [{"label": "A"}, {"label": "B"}]}

    async def run_native(**kwargs):
        kwargs["on_chunk"](text)
        return {"final": text, "clarify": clarify, "escalation": None, "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", run_native)
    await arslan.handle_user_message("cards", "question", lambda event: None)
    async with db_session.AsyncSessionLocal() as db:
        reply = [m for m in (await db.execute(select(ArslanMessage).where(
            ArslanMessage.conversation_id == "cards"))).scalars() if m.role == "arslan"][-1]
    assert reply.run_id is not None
    if (job := arslan._after_turn_tail.get("cards")) is not None:
        await job                                   # the post-turn job ends first ("finishing" until then)
    shown = await turn_undo.preview(reply.run_id)
    assert shown["conversation"] is True
    out = await turn_undo.undo(reply.run_id, last=shown["last_message_id"])
    assert out["messages"] == 2
    async with db_session.AsyncSessionLocal() as db:
        assert not (await db.execute(select(ArslanMessage).where(ArslanMessage.conversation_id == "cards"))).first()



async def test_a_job_result_inside_a_turn_does_not_make_it_another_runs(execution_db):
    """🟠2's rule counts replies of other runs, not a background job's result (it arrives whenever it ends)."""
    await _plain(execution_db, A, "start a long job")
    asked = await memory.add_message(A, "user", "meanwhile, a question")
    async with execution_db() as db:
        job_run = Run(conversation_id=A, user_message="job", status="done")
        answer_run = Run(conversation_id=A, user_message="meanwhile, a question", status="done")
        db.add_all([job_run, answer_run])
        await db.flush()
        db.add(ArslanMessage(conversation_id=A, role="arslan", content="job result", run_id=job_run.id,
                             job_outcome="done"))
        await db.flush()
        db.add(ArslanMessage(conversation_id=A, role="arslan", content="the answer", run_id=answer_run.id))
        await db.commit()
        answer = answer_run.id
    out = await turn_undo.undo(answer)
    assert out["messages"] == 3 and asked
    assert await _messages(execution_db, A) == [("user", "start a long job"), ("arslan", "done start a long job")]
