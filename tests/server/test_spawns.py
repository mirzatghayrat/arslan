"""What is left of the spawn REST endpoints."""
import pytest

from server.db.models import Spawn
from server.services import spawn_service


async def _create_spawn(client, name="beauty-guru"):
    # Seed a spawn directly via the service-backed test helper endpoint.
    return await client.post("/api/v1/_test/seed_spawn", json={"name": name})


@pytest.mark.asyncio
async def test_list_spawns_empty(client):
    resp = await client.get("/api/v1/spawns")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_spawn(client):
    await _create_spawn(client)
    listed = await client.get("/api/v1/spawns")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "beauty-guru"
    assert rows[0]["domain"] == "content-creator.xiaohongshu"


# Moved from test_spawn_delete.py when C7c-3a removed DELETE /spawns/{id} and spawn_service.delete_spawn.
def test_to_summary_carries_is_default():
    sp = Spawn(id=1, name="B", domain_category="x", capabilities=[], system_prompt="x", is_default=True)
    assert spawn_service.to_summary(sp).is_default is True
