import anyio
import pytest

from tests.server.conftest import build_ws_client


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(
        portal, tmp_path, monkeypatch,
        db_name="se.db", env={"ARSLAN_API_TOKEN": ""},
    )


def test_session_ended_triggers_distill_when_enabled(app_client, monkeypatch):
    import server.ws.arslan as wsmod
    called = {}
    async def fake_distill(cid):
        called["cid"] = cid
    monkeypatch.setattr(wsmod.distill_service, "distill_session", fake_distill)
    async def always_on(_s):
        return True
    monkeypatch.setattr(wsmod.settings_service, "distill_enabled", always_on)
    with app_client.websocket_connect("/ws/arslan/conv-x?token=") as ws:
        ws.send_json({"type": "session_ended", "conversation_id": "old-conv"})
        for _ in range(8):
            f = ws.receive_json()
            if f.get("type") == "session_ended_ack":
                break
    app_client.portal.call(anyio.sleep, 0.05)
    assert called.get("cid") == "old-conv"


def test_session_ended_skips_when_disabled(app_client, monkeypatch):
    import server.ws.arslan as wsmod
    called = {}
    async def fake_distill(cid):
        called["cid"] = cid
    monkeypatch.setattr(wsmod.distill_service, "distill_session", fake_distill)
    async def always_off(_s):
        return False
    monkeypatch.setattr(wsmod.settings_service, "distill_enabled", always_off)
    with app_client.websocket_connect("/ws/arslan/conv-y?token=") as ws:
        ws.send_json({"type": "session_ended", "conversation_id": "old-conv"})
        for _ in range(8):
            f = ws.receive_json()
            if f.get("type") == "session_ended_ack":
                break
    assert "cid" not in called
