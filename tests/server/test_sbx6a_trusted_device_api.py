"""SBX-6a: Settings adds a trusted local device through one lookup that pins its address (or refuses, with why)."""
from server.services import sandbox_proxy
from tests.server.test_proactive_api import client  # noqa: F401 — token-protected app client


async def test_a_lan_address_is_returned_pinned_and_a_public_one_refused(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sandbox_proxy, "own_addresses", lambda: frozenset())
    ok = await client.post("/api/v1/settings/trusted-devices/resolve", json={"host": "192.168.1.30"})
    assert ok.status_code == 200 and ok.json() == {"address": "192.168.1.30"}
    refused = await client.post("/api/v1/settings/trusted-devices/resolve", json={"host": "8.8.8.8"})
    assert refused.status_code == 400 and refused.json()["detail"] == {"code": "not_private"}
    empty = await client.post("/api/v1/settings/trusted-devices/resolve", json={"host": " "})
    assert empty.status_code == 400 and empty.json()["detail"] == {"code": "unresolvable"}


async def test_the_lookup_stores_nothing(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sandbox_proxy, "own_addresses", lambda: frozenset())
    await client.post("/api/v1/settings/trusted-devices/resolve", json={"host": "192.168.1.30"})
    settings = (await client.get("/api/v1/settings")).json()
    assert settings.get("sandbox_trusted_devices", "") == ""
