"""C8-4 (v0.1.63): session-end distillation, its switch, and the rest of the distill
chain are gone.

`session_ended` started distill_session in the background (ws/arslan.py), and
POST /spawns/{id}/complete-chat ran distill_from_signals. Neither could produce
anything on main: _distill_v2 returned `learning_disabled` unless a personal context
was bound to that expert, and neither a background task nor that REST handler binds
one. The `session_ended` frame itself stays and is still acked
(test_ws_session_ended, test_ws_reattach, test_phone_turn_cards).
"""
import importlib.util

from server.schemas import SettingsIn, SettingsOut
from server.services import replay_safety, settings_service

AUTH: dict[str, str] = {}


def test_the_distill_chain_and_its_setting_are_gone():
    for module in ("server.services.distill_service", "server.services.chat_lifecycle",
                   "server.services.prompts.distill"):
        assert importlib.util.find_spec(module) is None, module
    assert not hasattr(replay_safety, "should_not_curate")
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


async def test_the_complete_chat_route_is_gone(client):
    # Positive control: the spawns router itself still answers.
    assert (await client.get("/api/v1/spawns", headers=AUTH)).status_code == 200
    r = await client.post("/api/v1/spawns/1/complete-chat", headers=AUTH)
    assert r.status_code in (404, 405)


async def test_old_distill_rows_still_read_back_and_delete_cleanly(client, monkeypatch):
    """The tables stay (DELETE-BY v0.1.65). Rows written before C8-3/C8-4 (a `distill`
    or `distill_failed` or `curation_failed` timeline event, a `DistilledSession` marker
    with the sweep's give-up reason) must still display on the recap and still go when
    their conversation is deleted. Nothing may special-case them into a crash."""
    from sqlalchemy import func, select

    from server.db import session as db_session
    from server.db.models import ConversationEvent, DistilledSession

    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    cid = "old-distill-conv"
    async with client.db_maker() as s:
        for kind in ("distill", "distill_failed", "curation_failed"):
            s.add(ConversationEvent(conversation_id=cid, kind=kind, ref={"spawn_id": 3}, summary=kind))
        s.add(DistilledSession(conversation_id=cid, spawn_id=3, reason="curation_gave_up"))
        await s.commit()

    r = await client.get(f"/api/v1/conversations/{cid}/recap", headers=AUTH)
    assert r.status_code == 200, r.text
    assert {"distill", "distill_failed", "curation_failed"} <= {i["kind"] for i in r.json()["items"]}

    assert (await client.delete(f"/api/v1/conversations/{cid}", headers=AUTH)).status_code == 200
    async with client.db_maker() as s:
        left = await s.scalar(select(func.count()).select_from(DistilledSession)
                              .where(DistilledSession.conversation_id == cid))
    assert left == 0
