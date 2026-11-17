"""C7c-4 (v0.1.64): the last expert routes are gone: the equip popover's two (GET /spawns, PUT
/spawns/{id}/equipment) and the former-experts page's two (/experts/legacy, /experts/{id}/to-skill). The release
check's login probe moved to GET /conversations, which stays. The converter itself
(server/services/expert_conversion.py) went with C7c-5c: migration 0103 converts with frozen copies of it."""
import importlib.util

import pytest

GONE = {
    ("get", "/api/v1/spawns"),
    ("put", "/api/v1/spawns/{spawn_id}/equipment"),
    ("get", "/api/v1/experts/legacy"),
    ("post", "/api/v1/experts/{spawn_id}/to-skill"),
}
STAYS = {
    ("get", "/api/v1/conversations"),
    ("get", "/api/v1/memory/entries"),
    ("post", "/api/v1/memory/entries"),
}


@pytest.mark.asyncio
async def test_the_expert_routes_are_gone_and_the_probe_route_stays(client):
    paths = (await client.get("/openapi.json")).json()["paths"]
    served = {(method, path) for path, methods in paths.items() for method in methods}
    assert GONE & served == set()
    assert STAYS - served == set()


def test_the_route_modules_and_the_converter_are_gone():
    for module in ("server.api.spawns", "server.api.expert_conversion"):
        assert importlib.util.find_spec(module) is None, module
    assert importlib.util.find_spec("server.services.expert_conversion") is None
    from server import schemas
    from server.registry import service as registry_service

    assert not hasattr(schemas, "EquipmentUpdateIn")
    for name in ("equipment_for_spawn", "replace_user_equipment"):
        assert not hasattr(registry_service, name), name
