"""C7c-4 (v0.1.64): no new writes into an expert's own memory (scope `expert`), from any origin and through any
route. Since C7c-5c the scope is out of the contract (MemoryScope), 0103 moved the old entries to global, and its
triggers refuse the scope in the database (tests/server/test_migration_0103.py covers the move)."""
import pytest
from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite, decide_write
from server.db.models import MemoryEntry
from server.services.memory_repository import repository


def test_the_expert_scope_is_not_in_the_contract():
    with pytest.raises(ValidationError):
        MemoryScope(kind="expert", id="3")


def test_decide_write_still_takes_the_other_scopes():
    for scope in (MemoryScope(kind="global"), MemoryScope(kind="project", id="p"), MemoryScope(kind="domain", id="d")):
        assert decide_write(MemoryWrite(content="Use short answers", scope=scope), MemoryActor(origin="user")).status


@pytest.mark.asyncio
async def test_the_editor_route_refuses_a_new_expert_scope_entry_and_writes_nothing(client):
    body = {"content": "Use short answers", "scope": {"kind": "expert", "id": "3"}}
    resp = await client.post("/api/v1/memory/entries", json=body)
    assert resp.status_code == 422
    async with repository() as repo:
        assert await repo.list_entries() == []
    assert (await client.post("/api/v1/memory/entries",
                              json={**body, "scope": {"kind": "global", "id": None}})).status_code == 201


@pytest.mark.asyncio
async def test_the_database_refuses_moving_an_entry_into_the_expert_scope(client):
    created = (await client.post("/api/v1/memory/entries",
                                 json={"content": "Old expert note", "scope": {"kind": "global", "id": None}})).json()
    with pytest.raises(DBAPIError, match="memory_scope_retired"):
        async with repository() as repo:
            await repo.db.execute(update(MemoryEntry).where(MemoryEntry.id == created["id"]).values(
                scope_kind="expert", scope_id="3"))
    stay = {"expected_version": 1, "memory": {"content": "Edited", "scope": {"kind": "expert", "id": "3"}}}
    assert (await client.put(f"/api/v1/memory/entries/{created['id']}", json=stay)).status_code == 422
