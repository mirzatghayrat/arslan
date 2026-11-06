"""C7c-3a (v0.1.64): the expert-era routes with no caller are gone; what is in use until C7c-4 stays."""
import pytest

GONE = {
    ("get", "/api/v1/spawns/{spawn_id}"),
    ("delete", "/api/v1/spawns/{spawn_id}"),
    ("put", "/api/v1/spawns/{spawn_id}/config"),
    ("get", "/api/v1/spawns/{spawn_id}/knowledge"),
    ("delete", "/api/v1/spawns/{spawn_id}/knowledge"),
    ("put", "/api/v1/spawns/{spawn_id}/collections/{collection_id}"),
    ("delete", "/api/v1/spawns/{spawn_id}/collections/{collection_id}"),
    ("post", "/api/v1/facts/dedup"),
    ("post", "/api/v1/facts/classify"),
}
STAYS = {
    ("get", "/api/v1/spawns"),
    ("put", "/api/v1/spawns/{spawn_id}/equipment"),
    ("post", "/api/v1/spawns/{spawn_id}/knowledge"),
    ("get", "/api/v1/facts"),
}


@pytest.mark.asyncio
async def test_the_routes_with_no_caller_are_gone_and_the_ones_in_use_stay(client):
    paths = (await client.get("/openapi.json")).json()["paths"]
    served = {(method, path) for path, methods in paths.items() for method in methods}
    assert GONE & served == set()
    assert STAYS - served == set()
