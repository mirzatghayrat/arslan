"""Catalog endpoint: full transparency, assignable flag derived from tier+status."""
import pytest

from server.services import code_sandbox


@pytest.mark.asyncio
async def test_registry_lists_catalog_with_assignable_flags(client):
    resp = await client.get("/api/v1/registry")
    assert resp.status_code == 200
    body = resp.json()
    toolsets = {t["key"]: t for t in body["toolsets"]}
    skills = {s["key"]: s for s in body["skills"]}

    assert toolsets["web_search_scraping"]["assignable"] is True
    assert toolsets["session_search"]["assignable"] is False        # no wired tool yet
    assert toolsets["session_search"]["tier"] == "safe"             # listed, transparent
    assert skills["claude-code"]["assignable"] is False             # orchestrator tier
    assert skills["claude-code"]["tier"] == "orchestrator"          # listed, transparent
    assert skills["baoyu-infographic"]["assignable"] is True
    ws_tools = {t["key"]: t for t in toolsets["file_operations"]["tools"]}
    assert ws_tools["read_file"]["tier"] == "safe"
    assert ws_tools["write_file"]["tier"] == "orchestrator"


@pytest.mark.asyncio
async def test_registry_badges_code_sandbox_when_unsandboxed(client, monkeypatch):
    # P0-1 决定①b: when run_python is degraded to unsandboxed, the code_sandbox toolset
    # carries degraded=True + a warning so the capability page can badge it.
    monkeypatch.setattr(code_sandbox, "unsandboxed_active", lambda: True)
    body = (await client.get("/api/v1/registry")).json()
    cs = {t["key"]: t for t in body["toolsets"]}["code_sandbox"]
    assert cs["degraded"] is True and cs["warning"]

    monkeypatch.setattr(code_sandbox, "unsandboxed_active", lambda: False)
    body = (await client.get("/api/v1/registry")).json()
    cs = {t["key"]: t for t in body["toolsets"]}["code_sandbox"]
    assert cs["degraded"] is False and cs["warning"] is None


@pytest.mark.asyncio
async def test_registry_is_idempotent(client):
    resp1 = await client.get("/api/v1/registry")
    resp2 = await client.get("/api/v1/registry")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    body1 = resp1.json()
    body2 = resp2.json()
    assert body1 == body2
    assert len(body1["toolsets"]) == 9
