"""C7 step 2 (v0.1.63): the expert-create chain is gone.

The chain was POST /spawns/draft and POST /spawns -> spawn_service.create_from_draft, which
wrote a skill-pack to disk through arslan/spawn. Nothing reachable called it: the web's
api.createSpawn / api.draftSpawn had no component, and nothing read the skill-pack once the
dispatcher went. The live expert endpoints stay until v0.1.64 (C7 step 3):
GET /spawns, PUT /spawns/{id}/equipment, /experts/legacy.
"""
import importlib.util

from server.services import spawn_service

AUTH: dict[str, str] = {}


def test_the_chain_is_gone():
    for module in ("server.api.create", "server.services.spawn_drafter",
                   "server.services.equipment_service"):
        assert importlib.util.find_spec(module) is None, module
    for name in ("create_from_draft", "emit_skillpack", "reflect_equipment",
                 "create_spawn_unique", "build_system_prompt", "normalize_capabilities"):
        assert not hasattr(spawn_service, name), name
    # create_spawn stays: the boot seeding in server/main.py uses it.
    assert hasattr(spawn_service, "create_spawn")


async def test_the_create_routes_are_gone_and_the_live_ones_stay(client):
    # Positive control: the deferred live endpoint still answers.
    assert (await client.get("/api/v1/spawns", headers=AUTH)).status_code == 200
    assert (await client.post("/api/v1/spawns/draft", json={"description": "x"},
                              headers=AUTH)).status_code in (404, 405)
    assert (await client.post("/api/v1/spawns", json={"name": "x", "domain": "d"},
                              headers=AUTH)).status_code in (404, 405)
