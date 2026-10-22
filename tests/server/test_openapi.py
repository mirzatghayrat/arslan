"""Confirm the documented REST contract is present in the OpenAPI schema."""
import pytest

EXPECTED_PATHS = {
    "/api/v1/health",
    "/api/v1/spawns",
    "/api/v1/spawns/{spawn_id}",
    "/api/v1/spawns/{spawn_id}/config",
    "/api/v1/templates",
    "/api/v1/settings",
}


@pytest.mark.asyncio
async def test_openapi_lists_all_endpoints(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    paths = set(resp.json()["paths"].keys())
    missing = EXPECTED_PATHS - paths
    assert not missing, f"Missing documented endpoints: {missing}"


@pytest.mark.asyncio
async def test_evolution_endpoints_are_gone(client):
    """C2b-1 removed the evolution REST surface (no web entry point used it)."""
    resp = await client.get("/openapi.json")
    paths = resp.json()["paths"].keys()
    left = sorted(p for p in paths
                  if "/evolution" in p or p.endswith("/evolve")
                  or "/evolve/" in p or p.endswith("/feedback"))
    assert left == [], f"evolution endpoints still served: {left}"
