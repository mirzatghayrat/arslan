"""REST endpoint tests for provider-config CRUD + /settings/providers models field."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_provider_config_crud(client):
    r = await client.post("/api/v1/settings/provider-configs", json={
        "label": "A", "provider": "deepseek", "model": "deepseek-chat",
        "base_url": "", "api_key": "sk-aaaa1111bbbb"})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert r.json()["is_primary"] is True
    assert "..." in r.json()["api_key"]

    listed = (await client.get("/api/v1/settings/provider-configs")).json()
    assert any(c["id"] == cid for c in listed)

    r2 = await client.post("/api/v1/settings/provider-configs", json={
        "label": "B", "provider": "qwen", "model": "qwen-max",
        "base_url": "", "api_key": "sk-bbbb2222cccc"})
    cid2 = r2.json()["id"]

    await client.patch(f"/api/v1/settings/provider-configs/{cid2}/primary")
    configs = (await client.get("/api/v1/settings/provider-configs")).json()
    by_id = {c["id"]: c["is_primary"] for c in configs}
    assert by_id[cid2] is True and by_id[cid] is False

    del_r = await client.delete(f"/api/v1/settings/provider-configs/{cid}")
    assert del_r.status_code == 200


@pytest.mark.asyncio
async def test_providers_endpoint_includes_models(client):
    opts = (await client.get("/api/v1/settings/providers")).json()
    qwen = next(o for o in opts if o["key"] == "qwen")
    assert "qwen3.7-max" in qwen["models"]


@pytest.mark.asyncio
async def test_delete_last_config_returns_400(client):
    """Deleting the only remaining provider config must be refused with HTTP 400."""
    # Add exactly one config
    r = await client.post("/api/v1/settings/provider-configs", json={
        "label": "Solo", "provider": "deepseek", "model": "deepseek-chat",
        "base_url": "", "api_key": "sk-solo1111"})
    assert r.status_code == 200
    cid = r.json()["id"]

    # Attempt to delete the only config → must get 400
    del_r = await client.delete(f"/api/v1/settings/provider-configs/{cid}")
    assert del_r.status_code == 400, f"Expected 400, got {del_r.status_code}: {del_r.text}"
    assert "only" in del_r.json()["detail"].lower() or "last" in del_r.json()["detail"].lower()

    # The row must still exist
    listed = (await client.get("/api/v1/settings/provider-configs")).json()
    assert any(c["id"] == cid for c in listed), "Row was deleted despite 400 response"


@pytest.mark.asyncio
async def test_delete_non_last_config_succeeds(client):
    """Deleting one of two configs succeeds and promotes a survivor as primary."""
    r1 = await client.post("/api/v1/settings/provider-configs", json={
        "label": "A", "provider": "openai", "model": "gpt-4o",
        "base_url": "", "api_key": "sk-a1111"})
    cid1 = r1.json()["id"]
    r2 = await client.post("/api/v1/settings/provider-configs", json={
        "label": "B", "provider": "deepseek", "model": "deepseek-chat",
        "base_url": "", "api_key": "sk-b2222"})
    cid2 = r2.json()["id"]

    # Make A primary
    await client.patch(f"/api/v1/settings/provider-configs/{cid1}/primary")

    # Delete A (primary) — should succeed, B becomes primary
    del_r = await client.delete(f"/api/v1/settings/provider-configs/{cid1}")
    assert del_r.status_code == 200, f"Expected 200, got {del_r.status_code}: {del_r.text}"

    listed = (await client.get("/api/v1/settings/provider-configs")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == cid2
    assert listed[0]["is_primary"] is True
