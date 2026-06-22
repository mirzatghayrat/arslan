"""Tests for GET /settings/catalog endpoint."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_catalog_returns_list(client):
    r = await client.get("/api/v1/settings/catalog")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.asyncio
async def test_catalog_includes_anthropic(client):
    r = await client.get("/api/v1/settings/catalog")
    assert r.status_code == 200
    entries = {e["provider"]: e for e in r.json()}
    assert "anthropic" in entries
    cap = entries["anthropic"]["capabilities"]
    # reasoning should be present and high for anthropic
    assert "reasoning" in cap
    assert cap["reasoning"] >= 8


@pytest.mark.asyncio
async def test_catalog_entry_shape(client):
    r = await client.get("/api/v1/settings/catalog")
    assert r.status_code == 200
    entry = r.json()[0]
    assert "provider" in entry
    assert "capabilities" in entry
    assert "languages" in entry
    for dim in ("cost", "speed", "tool_calling", "reasoning", "long_context"):
        assert dim in entry["capabilities"]
