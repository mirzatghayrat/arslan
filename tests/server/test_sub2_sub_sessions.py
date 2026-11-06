"""SUB2 (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md): a sub-session's data. It only adds data, inheritance and
filtering; the user sees no change until SUB3 starts sub-sessions.

- A child's settings are read through its parents each time they are used, never copied once: when the parent
  tightens later, the child's next turn follows. Each setting takes the strictest value along the chain.
- A child can't be set looser than its chain (422 `sub_session_inherits`).
- A child never appears in a list of conversations, on the Mac or the phone, even while it runs.
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from server.db import session as db_session
from server.db.companion_models import ConversationContext, Project
from server.db.models import ArslanMessage
from server.services import background_jobs, sub_sessions, task_context

ROOT, CHILD, GRANDCHILD = "c-root", "c-child", "c-grandchild"


async def _root(db, **settings):
    async with db() as session:
        session.add(ConversationContext(id=ROOT, kind="chat", **settings))
        await session.commit()


async def _child(db, parent=ROOT, child=CHILD):
    async with db() as session:
        row = await sub_sessions.create_child(session, parent, child)
        await session.commit()
        return row.id


async def _set(db, cid, **values):
    async with db() as session:
        row = await session.get(ConversationContext, cid)
        for key, value in values.items():
            setattr(row, key, value)
        await session.commit()


async def _effective(db, cid):
    async with db() as session:
        return await sub_sessions.effective_settings(session, await session.get(ConversationContext, cid))


# -- creating one ------------------------------------------------------------------------------------------------

async def test_a_child_is_stored_as_a_sub_session_of_its_parent(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    async with execution_db() as session:
        row = await session.get(ConversationContext, CHILD)
    assert (row.kind, row.parent_id, row.owner_id) == ("sub", ROOT, "local")


async def test_a_child_starts_with_what_its_parent_allows(execution_db):
    await _root(execution_db, cloud_memory_allowed=True)
    await _child(execution_db)
    effective = await _effective(execution_db, CHILD)
    assert (effective.cloud_memory_allowed, effective.allow_sensitive) == (True, False)


async def test_a_parent_with_no_row_yet_gets_one_so_a_missing_parent_can_mean_deleted(execution_db):
    """An ordinary conversation has no row until a setting is changed. Its default row changes nothing about it."""
    await _child(execution_db, parent="c-never-set")
    async with execution_db() as session:
        parent = await session.get(ConversationContext, "c-never-set")
    assert parent is not None and parent.kind is None and parent.no_memory is False


async def test_a_temporary_conversation_cannot_start_one(execution_db):
    await _root(execution_db, temporary=True)
    with pytest.raises(sub_sessions.SubSessionError) as refused:
        await _child(execution_db)
    assert refused.value.code == "sub_session_from_temporary"


async def test_layers_are_counted_along_the_parents_and_stop_at_three(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    await _child(execution_db, parent=CHILD, child=GRANDCHILD)
    async with execution_db() as session:
        assert [await sub_sessions.depth(session, c) for c in (ROOT, CHILD, GRANDCHILD)] == [1, 2, 3]
    with pytest.raises(sub_sessions.SubSessionError) as refused:
        await _child(execution_db, parent=GRANDCHILD, child="c-fourth")
    assert refused.value.code == "sub_session_depth"


async def test_children_and_tree(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    await _child(execution_db, child="c-child-2")
    await _child(execution_db, parent=CHILD, child=GRANDCHILD)
    async with execution_db() as session:
        assert sorted(await sub_sessions.children(session, ROOT)) == [CHILD, "c-child-2"]
        assert sorted(await sub_sessions.tree(session, ROOT)) == sorted([ROOT, CHILD, "c-child-2", GRANDCHILD])


# -- inheritance -------------------------------------------------------------------------------------------------

def test_every_column_says_how_it_is_inherited():
    """A column added to ConversationContext without a line here fails: it would otherwise be silently the child's own."""
    assert set(sub_sessions.INHERITANCE) == {c.name for c in ConversationContext.__table__.columns}
    assert set(sub_sessions.INHERITANCE.values()) <= {"strictest_on", "strictest_off", "parent", "own"}


async def test_a_parent_that_tightens_later_reaches_the_child_at_once(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    assert (await _effective(execution_db, CHILD)).no_memory is False
    await _set(execution_db, ROOT, no_memory=True)
    assert (await _effective(execution_db, CHILD)).no_memory is True


async def test_a_grandparents_setting_reaches_the_grandchild(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    await _child(execution_db, parent=CHILD, child=GRANDCHILD)
    await _set(execution_db, ROOT, no_memory=True)
    assert (await _effective(execution_db, GRANDCHILD)).no_memory is True


@pytest.mark.parametrize("field", ["cloud_memory_allowed", "allow_sensitive"])
async def test_a_permission_needs_the_whole_chain(execution_db, field):
    await _root(execution_db, **{field: True})
    await _child(execution_db)
    assert getattr(await _effective(execution_db, CHILD), field) is True
    await _set(execution_db, ROOT, **{field: False})
    assert getattr(await _effective(execution_db, CHILD), field) is False


async def test_a_child_never_learns_and_its_own_tightening_holds(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    await _set(execution_db, CHILD, no_memory=True, no_learning=False)
    effective = await _effective(execution_db, CHILD)
    assert effective.no_learning is True and effective.no_memory is True
    assert (await _effective(execution_db, ROOT)).no_memory is False


async def test_the_project_follows_the_parent(execution_db):
    async with execution_db() as session:
        session.add(Project(id="p1", name="P"))
        await session.commit()
    await _root(execution_db, project_id="p1")
    await _child(execution_db)
    assert (await _effective(execution_db, CHILD)).project_id == "p1"
    async with execution_db() as session:
        assert (await session.get(ConversationContext, CHILD)).project_id == "p1"   # what files and rules read
    await _set(execution_db, CHILD, project_id=None)                # a row that went stale still reads the parent's
    assert (await _effective(execution_db, CHILD)).project_id == "p1"


@pytest.mark.parametrize("break_it", ["missing", "cycle"])
async def test_a_broken_chain_fails_closed(execution_db, break_it):
    await _root(execution_db, cloud_memory_allowed=True, allow_sensitive=True)
    await _child(execution_db)
    await _set(execution_db, CHILD, cloud_memory_allowed=True, allow_sensitive=True)
    if break_it == "missing":
        await _set(execution_db, CHILD, parent_id="c-deleted")
    else:
        await _set(execution_db, ROOT, parent_id=CHILD, kind="sub")
    effective = await _effective(execution_db, CHILD)
    assert (effective.no_memory, effective.no_learning) == (True, True)
    assert (effective.cloud_memory_allowed, effective.allow_sensitive) == (False, False)


async def test_an_ordinary_conversation_reads_its_own_row(execution_db):
    await _root(execution_db, no_memory=True, cloud_memory_allowed=True)
    effective = await _effective(execution_db, ROOT)
    assert (effective.no_memory, effective.cloud_memory_allowed, effective.no_learning) == (True, True, False)


# -- the turn reads it -------------------------------------------------------------------------------------------

async def test_the_next_turn_of_a_child_uses_what_the_parent_set(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    ctx = await task_context.load(CHILD, user_message="hello")
    assert (ctx.no_memory, ctx.no_learning) == (False, True)
    await _set(execution_db, ROOT, no_memory=True)
    assert (await task_context.load(CHILD, user_message="hello")).no_memory is True


async def test_a_child_turn_never_learns_whatever_its_row_says(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    await _set(execution_db, CHILD, no_learning=False)
    assert (await task_context.load(CHILD, user_message="hello")).no_learning is True


async def test_a_child_turn_cannot_use_what_only_it_allows(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    await _set(execution_db, CHILD, cloud_memory_allowed=True, allow_sensitive=True)
    ctx = await task_context.load(CHILD, user_message="hello")
    assert (ctx.cloud_memory_allowed, ctx.allow_sensitive) == (False, False)


async def test_a_childs_temporary_chain_is_read_each_time(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    assert await task_context.is_temporary(CHILD) is False
    await _set(execution_db, ROOT, temporary=True)
    assert await task_context.is_temporary(CHILD) is True
    assert (await task_context.load(CHILD, user_message="hello")).temporary is True


# -- the settings API --------------------------------------------------------------------------------------------

def _settings(version, **values):
    return {"schema_version": 1, "expected_version": version, **{"no_learning": True, **values}}


async def _api_family(client, monkeypatch, **parent):
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    await _root(client.db_maker, **parent)
    await _child(client.db_maker)


@pytest.mark.parametrize("parent, looser", [
    ({"no_memory": True}, {"no_memory": False}),
    ({"no_learning": True}, {"no_learning": False}),
    ({}, {"no_learning": False}),                                 # a sub-session never learns
    ({"cloud_memory_allowed": False}, {"cloud_memory_allowed": True}),
    ({"allow_sensitive": False}, {"allow_sensitive": True}),
], ids=["no-memory", "no-learning", "no-learning-always", "cloud", "sensitive"])
async def test_a_child_cannot_be_set_looser_than_its_chain(client, monkeypatch, parent, looser):
    await _api_family(client, monkeypatch, **parent)
    got = await client.put(f"/api/v1/conversations/{CHILD}/context", json=_settings(1, **{"no_memory": bool(parent.get("no_memory")), **looser}))
    assert got.status_code == 422
    assert got.json()["detail"]["code"] == "sub_session_inherits"


async def test_a_child_cannot_leave_its_parents_project(client, monkeypatch):
    await _api_family(client, monkeypatch)
    async with client.db_maker() as session:
        session.add(Project(id="p1", name="P"))
        await session.commit()
    got = await client.put(f"/api/v1/conversations/{CHILD}/context", json=_settings(1, project_id="p1"))
    assert got.status_code == 422 and got.json()["detail"]["code"] == "sub_session_inherits"


async def test_a_child_can_be_set_stricter(client, monkeypatch):
    await _api_family(client, monkeypatch)
    got = await client.put(f"/api/v1/conversations/{CHILD}/context", json=_settings(1, no_memory=True))
    assert got.status_code == 200 and got.json()["no_memory"] is True


async def test_moving_the_parent_to_a_project_moves_its_children(client, monkeypatch):
    await _api_family(client, monkeypatch)
    await _child(client.db_maker, parent=CHILD, child=GRANDCHILD)
    async with client.db_maker() as session:
        session.add(Project(id="p1", name="P"))
        await session.commit()
    got = await client.put(f"/api/v1/conversations/{ROOT}/context",
                           json={"schema_version": 1, "expected_version": 1, "project_id": "p1"})
    assert got.status_code == 200
    async with client.db_maker() as session:
        assert (await session.get(ConversationContext, CHILD)).project_id == "p1"
        assert (await session.get(ConversationContext, GRANDCHILD)).project_id == "p1"


# -- lists -------------------------------------------------------------------------------------------------------

async def _say(client, cid, text="hello"):
    async with client.db_maker() as session:
        session.add(ArslanMessage(conversation_id=cid, role="user", content=text, timestamp=datetime(2026, 11, 7, 12)))
        await session.commit()


async def test_a_child_is_in_no_conversation_list(client, monkeypatch):
    await _api_family(client, monkeypatch)
    await _say(client, ROOT)
    await _say(client, CHILD)
    ids = lambda rows: [r["conversation_id"] for r in rows]  # noqa: E731
    assert ids((await client.get("/api/v1/conversations")).json()) == [ROOT]
    phone = lambda rows: [r["id"] for r in rows["conversations"]]  # noqa: E731
    assert phone((await client.get("/api/v1/phone/conversations")).json()) == [ROOT]
    assert phone((await client.get("/api/v1/phone/conversations", params={"kind": "quick"})).json()) == []
    assert (await client.get("/api/v1/phone/live")).json()["conversation_ids"] == [ROOT]


async def test_a_child_is_not_in_its_projects_conversations(client, monkeypatch):
    await _api_family(client, monkeypatch)
    async with client.db_maker() as session:
        session.add(Project(id="p1", name="P"))
        await session.commit()
    await _set(client.db_maker, ROOT, project_id="p1")
    await _set(client.db_maker, CHILD, project_id="p1")
    await _say(client, ROOT)
    await _say(client, CHILD)
    rows = (await client.get("/api/v1/projects/p1/conversations")).json()
    assert [r["conversation_id"] for r in rows] == [ROOT]


async def test_a_running_child_stays_off_the_phone(client, monkeypatch):
    await _api_family(client, monkeypatch)
    await _say(client, ROOT)
    await _say(client, CHILD)
    def frame(cid):
        return {"conversation_id": cid, "goal": "g", "step": None, "criteria": []}
    jobs = [SimpleNamespace(conversation_id=cid, frame=lambda c=cid: frame(c)) for cid in (ROOT, CHILD, "c-other")]
    monkeypatch.setattr(background_jobs, "active", lambda: jobs)
    assert (await client.get("/api/v1/phone/live")).json()["conversation_ids"] == [ROOT, "c-other"]
    snapshot = (await client.get("/api/v1/phone/status")).json()
    assert [job["conversation_id"] for job in snapshot["jobs"]] == [ROOT, "c-other"]


async def test_the_phone_cannot_turn_a_child_into_a_chat(client, monkeypatch):
    await _api_family(client, monkeypatch)
    await _say(client, CHILD)
    got = await client.post(f"/api/v1/phone/conversations/{CHILD}/update", json={"kind": "chat"})
    assert got.status_code == 404
    async with client.db_maker() as session:
        assert (await session.get(ConversationContext, CHILD)).kind == "sub"
