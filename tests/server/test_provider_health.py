"""Provider-P4: tri-state connectivity probe + /health endpoint persistence.

probe() is exercised through httpx.MockTransport (repo idiom, see
tests/server/test_model_catalog.py). Endpoint tests monkeypatch
provider_health.probe so no network shape leaks into persistence tests.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import httpx

from arslan.llm.presets import expand_preset
from server.services import provider_health


# ---------------------------------------------------------------------------
# probe — state mapping
# ---------------------------------------------------------------------------


async def test_probe_non_empty_list_is_reachable_models():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "m-1"}, {"id": "m-2"}]})

    out = await provider_health.probe(
        "deepseek", "https://api.deepseek.com", "sk-x",
        transport=httpx.MockTransport(handler))
    assert out["state"] == "reachable_models"
    assert isinstance(out["latency_ms"], int)
    assert out["latency_ms"] >= 0
    assert out["detail"] is None


async def test_probe_empty_list_is_reachable_no_list():
    def handler(request):
        return httpx.Response(200, json={"data": []})

    out = await provider_health.probe(
        "deepseek", "https://api.deepseek.com", "sk-x",
        transport=httpx.MockTransport(handler))
    assert out["state"] == "reachable_no_list"


async def test_probe_http_401_is_reachable_no_list_with_status_detail():
    """The server ANSWERED (401) — HTTP-reachable, just no usable model list.
    Chat may still work (some gateways gate /models harder than /chat)."""
    def handler(request):
        return httpx.Response(401, json={"error": "bad key"})

    out = await provider_health.probe(
        "deepseek", "https://api.deepseek.com", "sk-bad",
        transport=httpx.MockTransport(handler))
    assert out["state"] == "reachable_no_list"
    assert "401" in (out["detail"] or "")


async def test_probe_connect_error_is_unreachable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    out = await provider_health.probe(
        "custom", "http://192.168.1.99:1234/v1", "",
        transport=httpx.MockTransport(handler))
    assert out["state"] == "unreachable"
    assert "refused" in (out["detail"] or "")


async def test_probe_hang_past_timeout_is_unreachable(monkeypatch):
    monkeypatch.setattr(provider_health, "REMOTE_TIMEOUT_S", 0.05)

    async def handler(request):
        await asyncio.sleep(30)
        return httpx.Response(200, json={"data": []})

    out = await asyncio.wait_for(
        provider_health.probe(
            "deepseek", "https://api.deepseek.com", "sk-x",
            transport=httpx.MockTransport(handler)),
        timeout=5)
    assert out["state"] == "unreachable"
    assert out["detail"]  # str(TimeoutError()) is "" — must still carry a name


# ---------------------------------------------------------------------------
# probe — local vs remote timeout selection
# ---------------------------------------------------------------------------


def test_timeout_local_hosts_get_local_timeout():
    assert provider_health._timeout_for(
        "custom", "http://localhost:1234/v1") == provider_health.LOCAL_TIMEOUT_S
    assert provider_health._timeout_for(
        "custom", "http://127.0.0.1:8000/v1") == provider_health.LOCAL_TIMEOUT_S
    # ollama with a blank base_url defaults to the LOCAL daemon
    assert provider_health._timeout_for(
        "ollama", "") == provider_health.LOCAL_TIMEOUT_S


def test_timeout_remote_hosts_get_remote_timeout():
    assert provider_health._timeout_for(
        "deepseek", "https://api.deepseek.com") == provider_health.REMOTE_TIMEOUT_S
    # native providers with a blank base_url default to their REMOTE official bases
    assert provider_health._timeout_for(
        "anthropic", "") == provider_health.REMOTE_TIMEOUT_S
    assert provider_health._timeout_for(
        "gemini", "") == provider_health.REMOTE_TIMEOUT_S


async def test_probe_local_host_uses_local_timeout(monkeypatch):
    """Behavioral proof: a hanging LOCAL server trips the LOCAL constant."""
    monkeypatch.setattr(provider_health, "LOCAL_TIMEOUT_S", 0.05)
    monkeypatch.setattr(provider_health, "REMOTE_TIMEOUT_S", 60.0)

    async def handler(request):
        await asyncio.sleep(30)
        return httpx.Response(200, json={"data": []})

    out = await asyncio.wait_for(
        provider_health.probe(
            "custom", "http://localhost:1234/v1", "",
            transport=httpx.MockTransport(handler)),
        timeout=5)
    assert out["state"] == "unreachable"


# ---------------------------------------------------------------------------
# POST /settings/provider-configs/{id}/health — persistence
# ---------------------------------------------------------------------------


async def _add_config(client, **over):
    payload = {"label": "A", "provider": "deepseek", "model": "deepseek-chat",
               "base_url": "", "api_key": "sk-aaaa1111bbbb"}
    payload.update(over)
    r = await client.post("/api/v1/settings/provider-configs", json=payload)
    assert r.status_code == 200
    return r.json()["id"]


async def test_health_endpoint_404_for_unknown_config(client):
    r = await client.post("/api/v1/settings/provider-configs/999999/health")
    assert r.status_code == 404


async def test_list_shows_null_health_before_first_probe(client):
    cid = await _add_config(client)
    listed = (await client.get("/api/v1/settings/provider-configs")).json()
    row = next(c for c in listed if c["id"] == cid)
    assert row["last_health"] is None
    assert row["last_health_at"] is None


async def test_health_endpoint_probes_persists_and_list_exposes(client, monkeypatch):
    cid = await _add_config(client)
    seen = {}

    async def fake_probe(provider, base_url, api_key, *, transport=None):
        seen["provider"], seen["base_url"], seen["api_key"] = provider, base_url, api_key
        return {"state": "reachable_models", "latency_ms": 42, "detail": None}

    monkeypatch.setattr(provider_health, "probe", fake_probe)
    r = await client.post(f"/api/v1/settings/provider-configs/{cid}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "reachable_models"
    assert body["latency_ms"] == 42
    assert body["detail"] is None
    assert body["last_health_at"] is not None

    # The probe received the config-level provider key + the expand_preset-resolved
    # base_url and the DECRYPTED key (mirrors the /models endpoint semantics).
    expected_base = expand_preset("deepseek", "deepseek-chat", "")[2]
    assert expected_base  # preset resolution really happened
    assert seen == {"provider": "deepseek", "base_url": expected_base,
                    "api_key": "sk-aaaa1111bbbb"}

    # Persisted on the row (re-read through a fresh session)
    from server.db.models import ProviderConfig
    async with client.db_maker() as s:
        row = await s.get(ProviderConfig, cid)
        assert row.last_health == "reachable_models"
        assert isinstance(row.last_health_at, datetime)

    # And the list endpoint exposes both fields
    listed = (await client.get("/api/v1/settings/provider-configs")).json()
    pub = next(c for c in listed if c["id"] == cid)
    assert pub["last_health"] == "reachable_models"
    assert pub["last_health_at"] == body["last_health_at"]


async def test_health_endpoint_persists_unreachable_state(client, monkeypatch):
    cid = await _add_config(client)

    async def fake_probe(provider, base_url, api_key, *, transport=None):
        return {"state": "unreachable", "latency_ms": None, "detail": "ConnectError"}

    monkeypatch.setattr(provider_health, "probe", fake_probe)
    r = await client.post(f"/api/v1/settings/provider-configs/{cid}/health")
    assert r.status_code == 200
    assert r.json()["state"] == "unreachable"
    assert r.json()["detail"] == "ConnectError"

    listed = (await client.get("/api/v1/settings/provider-configs")).json()
    pub = next(c for c in listed if c["id"] == cid)
    assert pub["last_health"] == "unreachable"
