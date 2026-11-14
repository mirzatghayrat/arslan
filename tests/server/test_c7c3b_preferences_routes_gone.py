"""C7c-3b (v0.1.64): the spawn preferences routes are gone, and so are their schemas. Expert-scope memory entries
are deleted through the companion memory route, which still syncs the deletion ledger."""
import pytest

GONE = {
    ("get", "/api/v1/spawns/{spawn_id}/preferences"),
    ("delete", "/api/v1/spawns/{spawn_id}/preferences"),
}
STAYS = {
    ("get", "/api/v1/spawns"),
    ("put", "/api/v1/spawns/{spawn_id}/equipment"),
    ("get", "/api/v1/memory/entries"),
    ("delete", "/api/v1/memory/entries/{entry_id}"),
}


@pytest.mark.asyncio
async def test_the_preferences_routes_are_gone_and_the_memory_routes_stay(client):
    paths = (await client.get("/openapi.json")).json()["paths"]
    served = {(method, path) for path, methods in paths.items() for method in methods}
    assert GONE & served == set()
    assert STAYS - served == set()


def test_the_preferences_schemas_are_gone():
    from server import schemas

    assert not hasattr(schemas, "PreferencesOut")
    assert not hasattr(schemas, "PreferenceDeleteIn")
