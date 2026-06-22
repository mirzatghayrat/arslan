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
    assert "qwen-max" in qwen["models"]
