"""Evolution stats + feedback submission tests."""
import pytest


async def _seed(client, name="evo-spawn"):
    await client.post("/api/v1/_test/seed_spawn", json={"name": name})
    return (await client.get("/api/v1/spawns")).json()[0]["id"]


@pytest.mark.asyncio
async def test_evolution_empty(client, tmp_path, monkeypatch):
    spawn_id = await _seed(client)
    resp = await client.get(f"/api/v1/spawns/{spawn_id}/evolution")
    assert resp.status_code == 200
    body = resp.json()
    assert body["feedback_count"] == 0
    assert body["active_rules"] == []


@pytest.mark.asyncio
async def test_submit_feedback_increments_count(client):
    spawn_id = await _seed(client)
    resp = await client.post(
        f"/api/v1/spawns/{spawn_id}/feedback",
        json={"message_id": 1, "user_action": "thumbs_down", "edits": {}},
    )
    assert resp.status_code == 201
    evo = await client.get(f"/api/v1/spawns/{spawn_id}/evolution")
    assert evo.json()["feedback_count"] == 1


@pytest.mark.asyncio
async def test_feedback_on_missing_spawn_404(client):
    resp = await client.post(
        "/api/v1/spawns/999/feedback",
        json={"user_action": "thumbs_up", "edits": {}},
    )
    assert resp.status_code == 404


def test_action_mapping():
    from server.services.evolution_service import map_user_action

    assert map_user_action("thumbs_up") == "accepted"
    assert map_user_action("thumbs_down") == "rejected"
    assert map_user_action("edit") == "edited"
    assert map_user_action("unknown") == "unknown"
