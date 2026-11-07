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
from sqlalchemy import select

from server.db import session as db_session
from server.db.companion_models import ConversationContext, Project
from server.db.models import ArslanMessage
from server.db.task_models import CompanionTask, TaskAttempt, TaskRevision
from server.registry.memory_executors import ConversationSearchExecutor
from server.services import background_jobs, personal_context as pc, phone_stats, sub_sessions, task_context

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


async def test_a_parent_with_no_row_yet_gets_one_so_a_missing_row_can_fail_closed(execution_db):
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


@pytest.fixture
def clean_phone_and_jobs():
    background_jobs._reset_for_tests()
    phone_stats._reset_for_tests()
    yield
    background_jobs._reset_for_tests()
    phone_stats._reset_for_tests()


async def _finished_task(client, cid, goal):
    now, task_id = datetime.utcnow(), f"t-{cid}"
    await _say(client, cid)
    async with client.db_maker() as session:
        for row in (CompanionTask(id=task_id, conversation_id=cid, attempt_id=f"a-{task_id}", budget={},
                                  privacy={"driver": {"kind": "background"}}, phase="succeeded", results=[],
                                  created_at=now, updated_at=now),
                    TaskRevision(task_id=task_id, revision=1, spec={"instruction": goal, "acceptance": []}),
                    TaskAttempt(id=f"a-{task_id}", task_id=task_id, number=1, spec_revision=1, run_ids=[])):
            session.add(row)
            await session.flush()
        await session.commit()


async def test_a_finished_child_task_is_not_in_the_phones_outcomes(client, monkeypatch, clean_phone_and_jobs):
    """With a child's id a phone can open it, and the card says a phone sees only the parent's summary and cards."""
    await _api_family(client, monkeypatch)
    await _finished_task(client, ROOT, "the parent's goal")
    await _finished_task(client, CHILD, "the child's goal")
    outcomes = (await client.get("/api/v1/phone/status")).json()["outcomes"]
    for scope in ("today", "week"):
        assert [t["conversation_id"] for t in outcomes[scope]["tasks"]] == [ROOT], scope


def _job(job_id, cid):
    job = background_jobs.Job(job_id=job_id, conversation_id=cid, goal=f"goal of {cid}", acceptance=[])
    job.phase = "running"
    background_jobs._jobs[job_id] = job


async def test_a_running_child_is_not_in_the_macs_list_of_jobs(client, monkeypatch, clean_phone_and_jobs):
    await _api_family(client, monkeypatch)
    _job("j-root", ROOT)
    _job("j-child", CHILD)
    _job("j-no-row", "c-no-row")                    # an ordinary conversation has no row until a setting changes
    everything = (await client.get("/api/v1/background-jobs")).json()
    assert [job["job_id"] for job in everything["jobs"]] == ["j-root", "j-no-row"]
    assert everything["active"] == 3                # what is running, as before
    # Opened from its parent, a child's window still asks for its own jobs.
    mine = (await client.get("/api/v1/background-jobs", params={"conversation_id": CHILD})).json()
    assert [job["job_id"] for job in mine["jobs"]] == ["j-child"] and mine["active"] == 3


# -- history search ----------------------------------------------------------------------------------------------

async def _searched(query):
    """What the search tool returns when another conversation calls it."""
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c-elsewhere", model_is_local=True)):
        out = await ConversationSearchExecutor().execute({"query": query})
    assert out["ok"] is True
    return {row["conversation_id"] for row in out["results"]}


@pytest.mark.parametrize("query", ["needle", "dl"], ids=["index", "like"])        # under three characters skips the index
@pytest.mark.parametrize("parent, found", [({}, {ROOT}), ({"no_memory": True}, set())], ids=["ordinary", "no-memory"])
async def test_the_search_tool_never_returns_a_child(execution_db, query, parent, found):
    from server.db.migrations.versions._0059_messages_fts import upgrade_sync
    await _root(execution_db, **parent)
    await _child(execution_db)
    async with execution_db() as session:
        session.add_all([ArslanMessage(conversation_id=cid, role="user", content="a needle here") for cid in (ROOT, CHILD)])
        await session.commit()
    async with execution_db.kw["bind"].begin() as connection:
        await connection.run_sync(upgrade_sync)
    assert await _searched(query) == found


@pytest.mark.parametrize("gone", ["deleted", "row-removed"])
async def test_a_child_stays_unsearchable_when_its_parent_is_gone(client, monkeypatch, gone):
    await _api_family(client, monkeypatch)
    await _say(client, ROOT, "a needle in the parent")
    await _say(client, CHILD, "a needle in the child")
    if gone == "deleted":
        assert (await client.delete(f"/api/v1/conversations/{ROOT}")).status_code == 200
    else:
        async with client.db_maker() as session:
            await session.delete(await session.get(ConversationContext, ROOT))
            await session.commit()
    async with client.db_maker() as session:          # nothing removes the child's own words yet (SUB5)
        assert await session.scalar(select(ArslanMessage.id).where(ArslanMessage.conversation_id == CHILD)) is not None
    assert CHILD not in await _searched("needle")


# -- what the review named as unpinned ---------------------------------------------------------------------------

async def test_a_grandchild_is_held_to_the_root_not_only_to_its_parent(client, monkeypatch):
    await _api_family(client, monkeypatch)
    await _child(client.db_maker, parent=CHILD, child=GRANDCHILD)
    await _set(client.db_maker, ROOT, no_memory=True)
    url = f"/api/v1/conversations/{GRANDCHILD}/context"
    refused = await client.put(url, json=_settings(1))
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "sub_session_inherits"
    assert (await client.put(url, json=_settings(1, no_memory=True))).status_code == 200


@pytest.mark.parametrize("parent_id", ["c-gone", None], ids=["parent-gone", "no-parent"])
async def test_a_child_with_no_chain_can_change_nothing(client, monkeypatch, parent_id):
    await _api_family(client, monkeypatch)
    await _set(client.db_maker, CHILD, parent_id=parent_id)
    got = await client.put(f"/api/v1/conversations/{CHILD}/context", json=_settings(1, no_memory=True))
    assert got.status_code == 422 and got.json()["detail"]["code"] == "sub_session_inherits"


async def test_a_parent_that_loosens_later_frees_its_own_setting_but_gives_no_permission(client, monkeypatch):
    await _api_family(client, monkeypatch, no_memory=True)
    await _set(client.db_maker, ROOT, no_memory=False, cloud_memory_allowed=True)
    effective = await _effective(client.db_maker, CHILD)
    assert (effective.no_memory, effective.cloud_memory_allowed) == (False, False)
    # Until the child's own setting asks for it, which the chain now allows.
    got = await client.put(f"/api/v1/conversations/{CHILD}/context", json=_settings(1, cloud_memory_allowed=True))
    assert got.status_code == 200
    assert (await _effective(client.db_maker, CHILD)).cloud_memory_allowed is True


async def test_a_child_that_started_with_a_permission_gets_it_back_with_its_parent(execution_db):
    await _root(execution_db, allow_sensitive=True)
    await _child(execution_db)
    await _set(execution_db, ROOT, allow_sensitive=False)
    assert (await _effective(execution_db, CHILD)).allow_sensitive is False
    await _set(execution_db, ROOT, allow_sensitive=True)
    assert (await _effective(execution_db, CHILD)).allow_sensitive is True


async def test_nothing_starts_below_a_chain_gone_temporary(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    await _set(execution_db, ROOT, temporary=True)
    with pytest.raises(sub_sessions.SubSessionError) as refused:
        await _child(execution_db, parent=CHILD, child=GRANDCHILD)
    assert refused.value.code == "sub_session_from_temporary"


async def test_a_child_turn_takes_its_project_and_what_follows_from_it_from_the_chain(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    saying = "remember that lunch is at noon"
    assert (await task_context.load(CHILD, user_message=saying)).allow_global_save is True
    async with execution_db() as session:
        session.add(Project(id="p1", name="P"))
        await session.commit()
    await _set(execution_db, ROOT, project_id="p1")                     # the child's own row still says none
    ctx = await task_context.load(CHILD, user_message=saying)
    assert (ctx.project_id, ctx.allow_global_save) == ("p1", False)


async def test_a_child_turn_in_a_chain_gone_temporary_uses_no_default_memory(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    assert (await task_context.load(CHILD, user_message="hello")).cloud_memory_default is True
    await _set(execution_db, ROOT, temporary=True)
    assert (await task_context.load(CHILD, user_message="hello")).cloud_memory_default is False


async def test_depth_counts_a_parent_that_is_gone(execution_db):
    await _root(execution_db)
    await _child(execution_db)
    await _set(execution_db, CHILD, parent_id="c-gone")
    async with execution_db() as session:
        assert await sub_sessions.depth(session, CHILD) == 2
        assert await sub_sessions.depth(session, "c-nobody") == 1


async def test_more_layers_than_exist_fail_closed(execution_db):
    allowed = {"cloud_memory_allowed": True, "allow_sensitive": True}
    await _root(execution_db, **allowed)
    await _child(execution_db)
    await _child(execution_db, parent=CHILD, child=GRANDCHILD)
    three = await _effective(execution_db, GRANDCHILD)
    assert (three.no_memory, three.cloud_memory_allowed, three.allow_sensitive) == (False, True, True)
    async with execution_db() as session:             # create_child refuses this, so only a row made by hand gets here
        session.add(ConversationContext(id="c-fourth", kind="sub", parent_id=GRANDCHILD, **allowed))
        await session.commit()
    four = await _effective(execution_db, "c-fourth")
    assert (four.no_memory, four.cloud_memory_allowed, four.allow_sensitive) == (True, False, False)
    async with execution_db() as session:
        assert await sub_sessions.depth(session, "c-fourth") == sub_sessions.MAX_DEPTH
