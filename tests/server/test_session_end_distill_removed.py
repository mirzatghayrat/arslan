"""C8-4 (v0.1.63): session-end distillation and its switch are gone.

`session_ended` started it in the background (ws/arslan.py). It could not produce
anything on main: _distill_v2 needs a personal context bound to the expert, and a
background task has none. The frame itself stays and is still acked
(test_ws_session_ended, test_ws_reattach, test_phone_turn_cards).
"""
from server.schemas import SettingsIn, SettingsOut
from server.services import distill_service, settings_service

AUTH: dict[str, str] = {}


def test_the_entry_point_and_its_setting_are_gone():
    for name in ("distill_session", "distill_session_detailed", "_distill_one", "DistillReport"):
        assert not hasattr(distill_service, name), name
    assert not hasattr(settings_service, "distill_enabled")
    assert "distill_on_session_end" not in settings_service._PLAIN_KEYS
    assert "distill_on_session_end" not in settings_service._BOOL_ACCESSORS
    assert "distill_on_session_end" not in SettingsIn.model_fields
    assert "distill_on_session_end" not in SettingsOut.model_fields


async def test_the_settings_api_no_longer_reports_or_stores_the_switch(client):
    """An old window that still sends it gets a 200 and nothing is stored."""
    r = await client.put("/api/v1/settings", json={"distill_on_session_end": False}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert "distill_on_session_end" not in r.json()
    assert "distill_on_session_end" not in (await client.get("/api/v1/settings", headers=AUTH)).json()
