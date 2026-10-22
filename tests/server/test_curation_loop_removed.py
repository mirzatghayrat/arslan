"""C8-3 (v0.1.63): the curation loop (整理层) and its switches are gone.

The loop ran every 15 minutes and never made a model call (C8 card, source). Its one
piece of real maintenance, the brain_usage_events prune, moved to usage_retention
first (test_usage_retention.py, which also boots the real lifespan and checks that
no curation loop runs).
"""
import importlib.util

from server.schemas import SettingsIn, SettingsOut
from server.services import settings_service

AUTH: dict[str, str] = {}


def test_the_module_and_its_settings_are_gone():
    assert importlib.util.find_spec("server.services.curation_loop") is None
    for field in ("curation_enabled", "curation_backfill_from"):
        assert field not in SettingsIn.model_fields
        assert field not in SettingsOut.model_fields
        assert field not in settings_service._PLAIN_KEYS
    assert "curation_enabled" not in settings_service._BOOL_ACCESSORS
    for name in ("curation_enabled", "curation_backfill_from",
                 "set_curation_backfill_from", "clear_curation_backfill_from"):
        assert not hasattr(settings_service, name), name


async def test_the_settings_api_no_longer_reports_or_stores_the_switch(client):
    """A client that still sends it (an old window, a stale tab) gets a 200 and nothing
    is stored; GET does not report it."""
    r = await client.put("/api/v1/settings", json={"curation_enabled": True}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert "curation_enabled" not in r.json()
    assert "curation_enabled" not in (await client.get("/api/v1/settings", headers=AUTH)).json()
