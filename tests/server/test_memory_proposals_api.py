"""Human adjudication API for memory_proposals under memory v2 (0.1.63 C2a-2).

The cards are v1's: nothing files new ones since C2a-2 removed the v1 rule layer and the v1 remember tool,
but old cards stay listed and can be dismissed. Accept materializes only a notes card (append or delete a
note — notes is still a table; user_facts and learnings are read-only views under v2). Any other card is
refused with versioned_memory_review_required (409): it has no target revision, so accepting it must not
count as approval of the current memory.

Error mapping under test (accept): no such card -> 404; already resolved or not a notes card -> 409; the
note is gone -> 410; a notes card this endpoint cannot materialize -> 422.
"""
from __future__ import annotations

from sqlalchemy import select

from server.db.models import MemoryProposal, Note


async def _seed_notes(client, *contents):
    async with client.db_maker() as db:
        rows = [Note(title=c[:20], content=c, tags=[]) for c in contents]
        db.add_all(rows)
        await db.commit()
        return [r.id for r in rows]


async def _seed_proposal(client, *, old_id=None, new_id=None, table_name="notes", kind="append_suspect",
                         status="pending", provenance=None, conversation_id=None):
    async with client.db_maker() as db:
        p = MemoryProposal(table_name=table_name, kind=kind, new_id=new_id, old_id=old_id if old_id is not None else 0,
                           reason="test", status=status, conversation_id=conversation_id,
                           provenance=provenance if provenance is not None else {"source_kind": "rule"})
        db.add(p)
        await db.commit()
        await db.refresh(p)
        return p.id


async def _status(client, pid):
    async with client.db_maker() as db:
        return (await db.get(MemoryProposal, pid)).status


# --------------------------------------------------------------------------- list

async def test_list_pending_shows_both_excerpts(client):
    new_id, old_id = await _seed_notes(client, "新内容比旧的长很多", "旧内容")
    pid = await _seed_proposal(client, new_id=new_id, old_id=old_id, kind="supersede_suspect")

    r = await client.get("/api/v1/brain/proposals?status=pending")
    assert r.status_code == 200
    row = next(x for x in r.json() if x["id"] == pid)
    assert row["new_excerpt"] == "新内容比旧的长很多"
    assert row["old_excerpt"] == "旧内容"
    assert row["status"] == "pending" and row["table_name"] == "notes"
    assert row["new_id"] == new_id and row["old_id"] == old_id


async def test_list_shows_none_excerpt_for_deleted_referent(client):
    new_id, old_id = await _seed_notes(client, "新", "旧")
    pid = await _seed_proposal(client, new_id=new_id, old_id=old_id)
    async with client.db_maker() as db:
        await db.delete(await db.get(Note, old_id))
        await db.commit()

    row = next(x for x in (await client.get("/api/v1/brain/proposals?status=pending")).json() if x["id"] == pid)
    assert row["old_excerpt"] is None and row["new_excerpt"] is not None


async def test_list_default_status_is_pending(client):
    pid = await _seed_proposal(client, status="dismissed")
    assert all(x["id"] != pid for x in (await client.get("/api/v1/brain/proposals")).json())


# --------------------------------------------------------------------------- accept

async def test_accept_404_no_such_proposal(client):
    assert (await client.post("/api/v1/brain/proposals/999999/accept")).status_code == 404


async def test_accept_409_already_resolved(client):
    pid = await _seed_proposal(client, status="dismissed", provenance={"content": "x"})
    assert (await client.post(f"/api/v1/brain/proposals/{pid}/accept")).status_code == 409


async def test_a_card_on_a_v1_table_is_refused_for_versioned_review(client):
    for table in ("user_facts", "learnings", "spawns"):
        pid = await _seed_proposal(client, table_name=table, kind="supersede_suspect", old_id=1, new_id=2)
        r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "versioned_memory_review_required", table
        assert await _status(client, pid) == "pending"            # the audit row stays as it was


async def test_accepting_a_note_append_creates_the_note(client):
    pid = await _seed_proposal(client, provenance={"content": "一条新笔记", "source_kind": "agentic"})
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    async with client.db_maker() as db:
        assert [n.content for n in (await db.execute(select(Note))).scalars()] == ["一条新笔记"]


async def test_a_note_append_without_content_is_422(client):
    pid = await _seed_proposal(client, provenance={"source_kind": "agentic"})
    assert (await client.post(f"/api/v1/brain/proposals/{pid}/accept")).status_code == 422


async def test_accepting_a_note_delete_removes_it_and_a_gone_note_is_410(client):
    (nid,) = await _seed_notes(client, "要删的笔记")
    pid = await _seed_proposal(client, kind="delete_suspect", old_id=nid)
    assert (await client.post(f"/api/v1/brain/proposals/{pid}/accept")).status_code == 200
    async with client.db_maker() as db:
        assert await db.get(Note, nid) is None
    again = await _seed_proposal(client, kind="delete_suspect", old_id=nid)
    assert (await client.post(f"/api/v1/brain/proposals/{again}/accept")).status_code == 410


async def test_any_other_kind_on_notes_is_422(client):
    (nid,) = await _seed_notes(client, "笔记")
    for kind in ("supersede_suspect", "edit_high_conf_suspect", "preference_overwrite_suspect", "made_up"):
        pid = await _seed_proposal(client, kind=kind, old_id=nid, provenance={"content": "x", "new_array": ["y"],
                                                                                "target_spawn_id": 1})
        assert (await client.post(f"/api/v1/brain/proposals/{pid}/accept")).status_code == 422, kind


async def test_accept_dismisses_only_same_conversation_siblings(client):
    """Two pending deletes of one note in ONE conversation describe a world that no longer exists once one
    is accepted; a card from ANOTHER conversation is separate material and stays pending."""
    (nid,) = await _seed_notes(client, "笔记")
    first = await _seed_proposal(client, kind="delete_suspect", old_id=nid, conversation_id="c1")
    same = await _seed_proposal(client, kind="delete_suspect", old_id=nid, conversation_id="c1")
    other = await _seed_proposal(client, kind="delete_suspect", old_id=nid, conversation_id="c2")
    assert (await client.post(f"/api/v1/brain/proposals/{first}/accept")).status_code == 200
    assert await _status(client, same) == "dismissed"
    assert await _status(client, other) == "pending"


async def test_accept_does_not_collide_on_the_old_id_zero_sentinel(client):
    """Target-less appends all carry old_id 0; accepting one must not dismiss the others."""
    a = await _seed_proposal(client, provenance={"content": "甲"}, conversation_id="c1")
    b = await _seed_proposal(client, provenance={"content": "乙"}, conversation_id="c1")
    assert (await client.post(f"/api/v1/brain/proposals/{a}/accept")).status_code == 200
    assert await _status(client, b) == "pending"


# --------------------------------------------------------------------------- dismiss

async def test_dismiss_success(client):
    pid = await _seed_proposal(client, table_name="user_facts", kind="supersede_suspect", old_id=1, new_id=2)
    r = await client.post(f"/api/v1/brain/proposals/{pid}/dismiss")
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed" and r.json()["resolved_at"] is not None


async def test_dismiss_404(client):
    assert (await client.post("/api/v1/brain/proposals/999999/dismiss")).status_code == 404


async def test_dismiss_409_already_resolved(client):
    pid = await _seed_proposal(client, status="accepted")
    assert (await client.post(f"/api/v1/brain/proposals/{pid}/dismiss")).status_code == 409


async def test_dismiss_dangling_allowed(client):
    """A card whose referent is gone can still be cleared away (unlike accept, which must refuse it)."""
    pid = await _seed_proposal(client, kind="delete_suspect", old_id=987654)
    assert (await client.post(f"/api/v1/brain/proposals/{pid}/dismiss")).status_code == 200
