"""C7c-4 (v0.1.64): no new writes into an expert's own memory (scope `expert`), from any origin and through any
route. The old entries stay readable and deletable until C7c-5's migration moves them to global."""
import pytest
from sqlalchemy import update

from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite, decide_write
from server.db.models import MemoryEntry
from server.services.memory_repository import repository


@pytest.mark.parametrize("actor", [
    MemoryActor(origin="user"), MemoryActor(origin="host", expert_id="3"),
    MemoryActor(origin="worker", expert_id="3"), MemoryActor(origin="extractor", expert_id="3"),
], ids=["user", "host", "worker", "extractor"])
def test_decide_write_refuses_the_expert_scope_for_every_origin(actor):
    with pytest.raises(MemoryError, match="memory_scope_denied"):
        decide_write(MemoryWrite(content="Use short answers", scope=MemoryScope(kind="expert", id="3")), actor)


def test_decide_write_still_takes_the_other_scopes():
    for scope in (MemoryScope(kind="global"), MemoryScope(kind="project", id="p"), MemoryScope(kind="domain", id="d")):
        assert decide_write(MemoryWrite(content="Use short answers", scope=scope), MemoryActor(origin="user")).status


@pytest.mark.asyncio
async def test_the_editor_route_refuses_a_new_expert_scope_entry_and_writes_nothing(client):
    body = {"content": "Use short answers", "scope": {"kind": "expert", "id": "3"}}
    resp = await client.post("/api/v1/memory/entries", json=body)
    assert resp.status_code == 403 and resp.json()["detail"] == {"code": "memory_scope_denied"}
    async with repository() as repo:
        assert await repo.list_entries() == []
    assert (await client.post("/api/v1/memory/entries",
                              json={**body, "scope": {"kind": "global", "id": None}})).status_code == 201


@pytest.mark.asyncio
async def test_an_old_expert_entry_can_be_moved_out_but_not_rewritten_in_place(client):
    created = (await client.post("/api/v1/memory/entries",
                                 json={"content": "Old expert note", "scope": {"kind": "global", "id": None}})).json()
    async with repository() as repo:          # old data: put in the expert scope directly
        await repo.db.execute(update(MemoryEntry).where(MemoryEntry.id == created["id"]).values(
            scope_kind="expert", scope_id="3"))
    stay = {"expected_version": 1, "memory": {"content": "Edited", "scope": {"kind": "expert", "id": "3"}}}
    refused = await client.put(f"/api/v1/memory/entries/{created['id']}", json=stay)
    assert refused.status_code == 403 and refused.json()["detail"] == {"code": "memory_scope_denied"}
    moved = await client.put(f"/api/v1/memory/entries/{created['id']}", json={
        "expected_version": 1, "confirm_scope_change": True,
        "memory": {"content": "Edited", "scope": {"kind": "global", "id": None}}})
    assert moved.status_code == 200 and moved.json()["scope"] == {"kind": "global", "id": None}
