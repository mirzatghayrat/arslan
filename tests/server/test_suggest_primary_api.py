"""Tests for GET /settings/suggest-primary quality-first recommendation endpoint."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_suggest_primary_recommends_quality(client):
    await client.post("/api/v1/settings/provider-configs", json={
        "label": "A", "provider": "anthropic", "model": "claude-sonnet-4-6",
        "base_url": "", "api_key": "sk-a1111"})
    await client.post("/api/v1/settings/provider-configs", json={
        "label": "B", "provider": "deepseek", "model": "deepseek-chat",
        "base_url": "", "api_key": "sk-b2222"})
    r = await client.get("/api/v1/settings/suggest-primary")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "anthropic"
    assert isinstance(body["rationale"], str) and body["rationale"]


@pytest.mark.asyncio
async def test_suggest_primary_returns_none_when_no_configs(client):
    r = await client.get("/api/v1/settings/suggest-primary")
    # No configs seeded — should return 204 or 200 null
    assert r.status_code in (200, 204)
    if r.status_code == 200:
        assert r.json() is None
