"""Spawn CRUD REST tests."""
import pytest


async def _create_spawn(client, name="beauty-guru"):
    # Seed a spawn directly via the service-backed test helper endpoint.
    return await client.post("/api/v1/_test/seed_spawn", json={"name": name})


@pytest.mark.asyncio
async def test_list_spawns_empty(client):
    resp = await client.get("/api/v1/spawns")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_and_get_spawn(client):
    await _create_spawn(client)
    listed = await client.get("/api/v1/spawns")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "beauty-guru"
    assert rows[0]["domain"] == "content-creator.xiaohongshu"

    spawn_id = rows[0]["id"]
    detail = await client.get(f"/api/v1/spawns/{spawn_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["system_prompt"]
    assert body["messages"] == []


@pytest.mark.asyncio
async def test_get_missing_spawn_404(client):
    resp = await client.get("/api/v1/spawns/999")
    assert resp.status_code == 404
    assert resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_config(client):
    await _create_spawn(client)
    spawn_id = (await client.get("/api/v1/spawns")).json()[0]["id"]
    resp = await client.put(
        f"/api/v1/spawns/{spawn_id}/config",
        json={"persona_tone": "playful", "system_prompt": "Be playful."},
    )
    assert resp.status_code == 200
    assert resp.json()["persona_tone"] == "playful"

    detail = await client.get(f"/api/v1/spawns/{spawn_id}")
    assert detail.json()["system_prompt"] == "Be playful."


@pytest.mark.asyncio
async def test_delete_spawn(client):
    await _create_spawn(client)
    spawn_id = (await client.get("/api/v1/spawns")).json()[0]["id"]
    resp = await client.delete(f"/api/v1/spawns/{spawn_id}")
    assert resp.status_code == 204
    assert (await client.get("/api/v1/spawns")).json() == []
