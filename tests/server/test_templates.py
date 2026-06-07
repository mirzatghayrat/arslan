"""Templates listing endpoint test."""
import pytest


@pytest.mark.asyncio
async def test_list_templates_returns_official(client):
    resp = await client.get("/api/v1/templates")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    sample = rows[0]
    assert "name" in sample and "domain" in sample and "tags" in sample
