"""Catalog endpoint: full transparency, assignable flag derived from tier+status."""
import pytest


@pytest.mark.asyncio
async def test_registry_lists_catalog_with_assignable_flags(client):
    resp = await client.get("/api/v1/registry")
    assert resp.status_code == 200
    body = resp.json()
    toolsets = {t["key"]: t for t in body["toolsets"]}
    skills = {s["key"]: s for s in body["skills"]}

    assert toolsets["web_search_scraping"]["assignable"] is True
    assert toolsets["code_execution"]["assignable"] is False        # orchestrator tier
    assert toolsets["code_execution"]["tier"] == "orchestrator"     # listed, transparent
    assert toolsets["memory"]["assignable"] is False                # absorbed
    assert skills["claude-code"]["assignable"] is False
    assert skills["baoyu-infographic"]["assignable"] is True
    ws_tools = {t["key"]: t for t in toolsets["file_operations"]["tools"]}
    assert ws_tools["read_file"]["tier"] == "safe"
    assert ws_tools["write_file"]["tier"] == "orchestrator"


@pytest.mark.asyncio
async def test_registry_is_idempotent(client):
    resp1 = await client.get("/api/v1/registry")
    resp2 = await client.get("/api/v1/registry")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    body1 = resp1.json()
    body2 = resp2.json()
    assert body1 == body2
    assert len(body1["toolsets"]) == 27
