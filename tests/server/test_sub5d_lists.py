"""SUB5d (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md): the Mac's window shows sub-sessions as a tree.

- The Mac's conversation list returns sub-sessions too, each with its `parent_id` and a state the sidebar's status
  icon reads (a card waiting for the user reads "waiting").
- Every phone route still leaves them out: the phone's list, its quick-question list and its live list.
- A project's conversations list a commander's tree, each sub-session with its parent.
- The tree's spend, as the tree's limit counts it, for the line in the commander's conversation.
"""
import uuid
from datetime import datetime

from server.db import session as db_session
from server.db.companion_models import ConversationContext, Project
from server.db.models import ArslanMessage
from server.db.task_models import CompanionTask, TaskAttempt, TaskRevision
from server.services import sub_sessions

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
