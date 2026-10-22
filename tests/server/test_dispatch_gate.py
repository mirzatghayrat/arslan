"""The evolution spend settings are gone from the settings API.

C2b-2 took `evolution_auto` / `evolution_max_dispatches` off GET/PUT; C7b-1 deleted the
manual evolve path whose spend gate was the last reader. The old token-cap key stays gone
too: it was deleted, not renamed, because a renamed key with a new unit would turn a stored
token cap into a meaningless dispatch cap.
"""
from __future__ import annotations

from server.services import settings_service

AUTH: dict[str, str] = {}


async def test_evolution_settings_are_not_served(client):
    """C2b-2: evolution_auto and evolution_max_dispatches left the settings surface. GET
    no longer reports them, and an old client that still PUTs them gets a 200 with the
    fields ignored (SettingsIn has no `extra=forbid`), not a 422."""
    r = await client.put("/api/v1/settings",
                         json={"evolution_auto": "on", "evolution_max_dispatches": 250},
                         headers=AUTH)
    assert r.status_code == 200, r.text
    body = (await client.get("/api/v1/settings", headers=AUTH)).json()
    assert "evolution_auto" not in body
    assert "evolution_max_dispatches" not in body


async def test_the_old_token_cap_key_is_gone(client):
    """Deleted, not renamed. Renaming while changing the unit is a silent-corruption trap:
    a stored 30,000,000 would become a '30 million dispatch' cap, which is no cap at all,
    and no conversion is honest because the token-per-dispatch figure is exactly what we
    do not reliably know."""
    body = (await client.get("/api/v1/settings", headers=AUTH)).json()
    assert "evolution_max_est_tokens" not in body
    assert not hasattr(settings_service, "evolution_max_est_tokens")
