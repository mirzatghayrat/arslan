"""SUB5d (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md): the Mac's window shows sub-sessions as a tree.

- The Mac's conversation list returns sub-sessions too, each with its `parent_id` and a state the sidebar's status
  icon reads (a card waiting for the user reads "waiting").
- Every phone route still leaves them out: the phone's list, its quick-question list and its live list.
- A project's conversations list a commander's tree, each sub-session with its parent.
- The tree's spend, as the tree's limit counts it, for the line in the commander's conversation.
"""
import uuid
from datetime import datetime
from types import SimpleNamespace

from server.db import session as db_session
from server.db.companion_models import ConversationContext, Project
from server.db.models import ArslanMessage
from server.db.task_models import CompanionTask, TaskAttempt, TaskRevision
from server.services import background_jobs, sub_sessions

ROOT, CHILD, GRANDCHILD = "c-root", "c-child", "c-grandchild"


async def _family(client, monkeypatch, **root):
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as session:
        session.add(ConversationContext(id=ROOT, kind="chat", **root))
        await session.commit()
    for parent, child in ((ROOT, CHILD), (CHILD, GRANDCHILD)):
        async with client.db_maker() as session:
            await sub_sessions.create_child(session, parent, child)
            await session.commit()
    for cid in (ROOT, CHILD, GRANDCHILD):
        async with client.db_maker() as session:
            session.add(ArslanMessage(conversation_id=cid, role="user", content=f"say {cid}",
                                      timestamp=datetime(2026, 11, 7, 12)))
            await session.commit()


async def test_the_macs_list_returns_sub_sessions_with_their_parent(client, monkeypatch):
    await _family(client, monkeypatch)
    rows = {r["conversation_id"]: r for r in (await client.get("/api/v1/conversations")).json()}
    assert set(rows) == {ROOT, CHILD, GRANDCHILD}
    assert (rows[ROOT]["parent_id"], rows[CHILD]["parent_id"], rows[GRANDCHILD]["parent_id"]) == (None, ROOT, CHILD)
    assert rows[CHILD]["title"] == f"say {CHILD}"


async def test_a_sub_session_whose_card_waits_reads_waiting(client, monkeypatch):
    await _family(client, monkeypatch)
    with sub_sessions.waiting_on_user(CHILD):
        rows = {r["conversation_id"]: r for r in (await client.get("/api/v1/conversations")).json()}
    assert rows[CHILD]["state"] == "waiting"
    assert rows[GRANDCHILD]["state"] != "waiting"
    after = {r["conversation_id"]: r for r in (await client.get("/api/v1/conversations")).json()}
    assert after[CHILD]["state"] != "waiting"


async def test_the_list_says_how_an_ended_sub_session_ended(client, monkeypatch):
    """A stop, a restart and a job that didn't get there each read apart from a finished one (the status icon's label)."""
    await _family(client, monkeypatch)
    async with client.db_maker() as session:
        for cid, outcome in ((ROOT, "done"), (CHILD, "stopped"), (GRANDCHILD, "interrupted")):
            session.add(ArslanMessage(conversation_id=cid, role="arslan", content="result", job_outcome=outcome,
                                      timestamp=datetime(2026, 11, 7, 13)))
        await session.commit()
    rows = {r["conversation_id"]: r for r in (await client.get("/api/v1/conversations")).json()}
    assert [(rows[c]["state"], rows[c]["outcome"]) for c in (CHILD, GRANDCHILD)] == [
        ("failed", "stopped"), ("unfinished", "interrupted")]
    assert rows[ROOT]["outcome"] == "done"
    phone = (await client.get("/api/v1/phone/conversations")).json()["conversations"]
    assert all("outcome" not in r for r in phone)


async def test_a_finished_sub_session_still_reporting_reads_at_work(client, monkeypatch):
    """Its job has finished but its report isn't delivered yet: the delete refuses it (409), so the list says so."""
    await _family(client, monkeypatch)
    async with client.db_maker() as session:
        session.add(ArslanMessage(conversation_id=CHILD, role="arslan", content="result", job_outcome="done",
                                  timestamp=datetime(2026, 11, 7, 13)))
        await session.commit()
    monkeypatch.setattr(background_jobs, "unreported", lambda: [SimpleNamespace(conversation_id=CHILD)])
    rows = {r["conversation_id"]: r for r in (await client.get("/api/v1/conversations")).json()}
    assert (rows[CHILD]["state"], rows[CHILD]["reporting"]) == ("working", True)
    assert rows[GRANDCHILD]["reporting"] is False
    phone = (await client.get("/api/v1/phone/conversations")).json()["conversations"]
    assert all("reporting" not in r for r in phone)


async def test_a_sub_session_a_restart_found_queued_reads_interrupted(client, monkeypatch):
    """#819's list: queued at the restart, it has no job and no message of its own; SUB5a's row says interrupted
    (`report_restart`), and so does the list. One the restart never touched reads as before."""
    await _family(client, monkeypatch)
    async with client.db_maker() as session:
        (await session.get(ConversationContext, CHILD)).sub_state = sub_sessions.INTERRUPTED
        (await session.get(ConversationContext, GRANDCHILD)).sub_state = None
        await session.commit()
    rows = {r["conversation_id"]: r for r in (await client.get("/api/v1/conversations")).json()}
    assert (rows[CHILD]["state"], rows[CHILD]["outcome"]) == ("unfinished", "interrupted")
    assert (rows[GRANDCHILD]["state"], rows[GRANDCHILD]["outcome"]) == ("idle", None)


async def test_a_running_sub_session_reads_working_not_reporting(client, monkeypatch):
    """#819's list: `unreported()` holds running jobs too, so only a row that isn't already at work is relabelled."""
    from server.services import run_registry
    await _family(client, monkeypatch)
    monkeypatch.setattr(background_jobs, "unreported", lambda: [SimpleNamespace(conversation_id=CHILD)])
    monkeypatch.setattr(run_registry, "active_for", lambda cid: cid == CHILD)
    rows = {r["conversation_id"]: r for r in (await client.get("/api/v1/conversations")).json()}
    assert (rows[CHILD]["state"], rows[CHILD]["reporting"]) == ("working", False)


async def test_the_spend_of_an_unknown_conversation_is_not_found(client, monkeypatch):
    await _family(client, monkeypatch)
    assert (await client.get("/api/v1/conversations/c-nobody/sub-sessions/spend")).status_code == 404


async def test_the_spend_of_a_deleted_conversation_is_not_found(client, monkeypatch):
    """#819's list: SUB5a's tombstone reads as no conversation, not as one that spent nothing."""
    await _family(client, monkeypatch)
    async with client.db_maker() as session:
        await sub_sessions.tombstone(session, [CHILD])
        await session.commit()
    assert (await client.get(f"/api/v1/conversations/{CHILD}/sub-sessions/spend")).status_code == 404
    assert (await client.get(f"/api/v1/conversations/{ROOT}/sub-sessions/spend")).status_code == 200


async def test_every_phone_route_still_hides_sub_sessions(client, monkeypatch):
    await _family(client, monkeypatch)
    phone = (await client.get("/api/v1/phone/conversations")).json()["conversations"]
    assert [r["id"] for r in phone] == [ROOT]
    assert all("parent_id" not in r for r in phone)
    quick = (await client.get("/api/v1/phone/conversations", params={"kind": "quick"})).json()["conversations"]
    assert quick == []
    assert (await client.get("/api/v1/phone/live")).json()["conversation_ids"] == [ROOT]


async def test_a_projects_conversations_carry_the_commanders_tree(client, monkeypatch):
    await _family(client, monkeypatch)
    async with client.db_maker() as session:
        session.add(Project(id="p1", name="P"))
        await session.commit()
    got = await client.put(f"/api/v1/conversations/{ROOT}/context",
                           json={"schema_version": 1, "expected_version": 1, "project_id": "p1"})
    assert got.status_code == 200
    rows = {r["conversation_id"]: r for r in (await client.get("/api/v1/projects/p1/conversations")).json()}
    assert set(rows) == {ROOT, CHILD, GRANDCHILD}
    assert (rows[ROOT]["parent_id"], rows[CHILD]["parent_id"], rows[GRANDCHILD]["parent_id"]) == (None, ROOT, CHILD)


async def _spent(cid, usd, db_maker):
    now, task_id = datetime.utcnow(), f"t-{uuid.uuid4()}"
    async with db_maker() as db:
        for row in (CompanionTask(id=task_id, conversation_id=cid, attempt_id=f"a-{task_id}", privacy={},
                                  budget={"spend": {"usd": usd, "usd_cap": 2.0, "unpriced_requests": 0}},
                                  phase="succeeded", results=[], created_at=now, updated_at=now),
                    TaskRevision(task_id=task_id, revision=1, spec={"instruction": "x", "acceptance": []}),
                    TaskAttempt(id=f"a-{task_id}", task_id=task_id, number=1, spec_revision=1, run_ids=[])):
            db.add(row)
            await db.flush()
        await db.commit()


async def test_the_trees_spend_is_its_sub_sessions_not_the_commanders_own(client, monkeypatch):
    await _family(client, monkeypatch)
    await _spent(CHILD, 1.25, client.db_maker)
    await _spent(GRANDCHILD, 0.5, client.db_maker)
    await _spent(ROOT, 40.0, client.db_maker)                  # the commander's own turn: not the tree's
    for cid in (ROOT, CHILD, GRANDCHILD):                     # read from anywhere in the tree, it is the whole tree's
        got = (await client.get(f"/api/v1/conversations/{cid}/sub-sessions/spend")).json()
        assert got == {"spent_usd": 1.75}
