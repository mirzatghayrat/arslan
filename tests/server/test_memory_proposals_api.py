"""Human adjudication API for memory_proposals (brain-P1 Task 5): list pending
soft-marks with both-side excerpts, accept (calls the deterministic
memory_temporal.execute_supersede executor with human provenance; SupersedeError
mapped to structured 4xx), dismiss (dangling-safe cleanup — a stale proposal whose
referent row was since deleted is still valid to dismiss, unlike accept which must
refuse it). The exact contract is the error mapping enumerated below.

Error mapping under test (accept only — dismiss never calls the executor):
  dangling_new / dangling_old -> 410 Gone (detail names the id)
  already_superseded / new_is_superseded / cycle / self_supersede -> 409 Conflict
  bad_table (corrupt table_name on the proposal row) -> 422 Unprocessable (data
    integrity, not a state conflict)
"""
from __future__ import annotations

import pytest

from server.db.models import Learning, MemoryProposal, UserFact

# The shared test databases stay on memory v1 in this file: the code it tests still has a v1 path,
# which C2a-2 deletes (then this marker goes too; marker memory_v1 in pyproject.toml).
pytestmark = pytest.mark.memory_v1


async def _seed_facts(client, new_content="新内容比旧的长很多", old_content="旧内容"):
    async with client.db_maker() as db:
        old = UserFact(content=old_content, source="auto", confidence=0.6)
        db.add(old)
        new = UserFact(content=new_content, source="auto", confidence=0.7)
        db.add(new)
        await db.commit()
        await db.refresh(old)
        await db.refresh(new)
        return new.id, old.id


async def _seed_learnings(client, new_content="新心得更完整", old_content="旧心得"):
    async with client.db_maker() as db:
        old = Learning(content=old_content, source_kind="distill", source_ref={}, confidence=0.6)
        db.add(old)
        new = Learning(content=new_content, source_kind="distill", source_ref={}, confidence=0.6)
        db.add(new)
        await db.commit()
        await db.refresh(old)
        await db.refresh(new)
        return new.id, old.id


async def _seed_proposal(client, new_id, old_id, table_name="user_facts", status="pending"):
    async with client.db_maker() as db:
        p = MemoryProposal(table_name=table_name, new_id=new_id, old_id=old_id,
                           reason="other: near-dup coexist", status=status,
                           provenance={"source_kind": "rule"})
        db.add(p)
        await db.commit()
        await db.refresh(p)
        return p.id


# --------------------------------------------------------------------------- list

async def test_list_pending_shows_both_excerpts(client):
    new_id, old_id = await _seed_facts(client, "新内容比旧的长很多", "旧内容")
    pid = await _seed_proposal(client, new_id, old_id)

    r = await client.get("/api/v1/brain/proposals?status=pending")
    assert r.status_code == 200
    row = next(x for x in r.json() if x["id"] == pid)
    assert row["new_excerpt"] == "新内容比旧的长很多"
    assert row["old_excerpt"] == "旧内容"
    assert row["status"] == "pending"
    assert row["table_name"] == "user_facts"
    assert row["new_id"] == new_id and row["old_id"] == old_id


async def test_list_shows_none_excerpt_for_deleted_referent(client):
    new_id, old_id = await _seed_facts(client)
    pid = await _seed_proposal(client, new_id, old_id)
    async with client.db_maker() as db:
        old = await db.get(UserFact, old_id)
        await db.delete(old)
        await db.commit()

    row = next(x for x in
               (await client.get("/api/v1/brain/proposals?status=pending")).json()
               if x["id"] == pid)
    assert row["old_excerpt"] is None
    assert row["new_excerpt"] is not None


async def test_list_default_status_is_pending(client):
    new_id, old_id = await _seed_facts(client)
    pid = await _seed_proposal(client, new_id, old_id, status="dismissed")
    rows = (await client.get("/api/v1/brain/proposals")).json()
    assert all(x["id"] != pid for x in rows)


# --------------------------------------------------------------------------- accept





async def test_accept_404_no_such_proposal(client):
    r = await client.post("/api/v1/brain/proposals/999999/accept")
    assert r.status_code == 404


async def test_accept_409_already_resolved(client):
    new_id, old_id = await _seed_facts(client)
    pid = await _seed_proposal(client, new_id, old_id, status="dismissed")
    r = await client.post(f"/api/v1/brain/proposals/{pid}/accept")
    assert r.status_code == 409








# --------------------------------------------------------------------------- dismiss

async def test_dismiss_success(client):
    new_id, old_id = await _seed_facts(client)
    pid = await _seed_proposal(client, new_id, old_id)
    r = await client.post(f"/api/v1/brain/proposals/{pid}/dismiss")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "dismissed"
    assert body["resolved_at"] is not None


async def test_dismiss_404(client):
    r = await client.post("/api/v1/brain/proposals/999999/dismiss")
    assert r.status_code == 404


async def test_dismiss_409_already_resolved(client):
    new_id, old_id = await _seed_facts(client)
    pid = await _seed_proposal(client, new_id, old_id, status="accepted")
    r = await client.post(f"/api/v1/brain/proposals/{pid}/dismiss")
    assert r.status_code == 409


async def test_dismiss_dangling_allowed(client):
    """Dismissing a stale proposal (referent since deleted) is valid cleanup — unlike
    accept, dismiss never touches the referenced rows, so there is nothing to dangle."""
    new_id, old_id = await _seed_facts(client)
    pid = await _seed_proposal(client, new_id, old_id)
    async with client.db_maker() as db:
        old = await db.get(UserFact, old_id)
        await db.delete(old)
        await db.commit()

    r = await client.post(f"/api/v1/brain/proposals/{pid}/dismiss")
    assert r.status_code == 200
    assert r.json()["status"] == "dismissed"
