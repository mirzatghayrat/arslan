"""Evolution stats + feedback submission tests."""


async def _seed(client, name="evo-spawn"):
    await client.post("/api/v1/_test/seed_spawn", json={"name": name})
    return (await client.get("/api/v1/spawns")).json()[0]["id"]


def test_action_mapping():
    from server.services.evolution_service import map_user_action

    assert map_user_action("thumbs_up") == "accepted"
    assert map_user_action("thumbs_down") == "rejected"
    assert map_user_action("edit") == "edited"
    assert map_user_action("unknown") == "unknown"
