import pytest

from tests.server.conftest import build_ws_client


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(
        portal, tmp_path, monkeypatch,
        db_name="se.db", env={"ARSLAN_API_TOKEN": ""},
    )


def test_session_ended_is_acked_and_starts_nothing(app_client):
    """C8-4 (v0.1.63): the frame used to start session-end distillation. It now only
    acks, because clients still send it and wait for the reply."""
    import server.ws.arslan as wsmod

    assert not hasattr(wsmod, "distill_service")
    with app_client.websocket_connect("/ws/arslan/conv-x?token=") as ws:
        ws.send_json({"type": "session_ended", "conversation_id": "old-conv"})
        for _ in range(8):
            f = ws.receive_json()
            if f.get("type") == "session_ended_ack":
                break
    assert f == {"type": "session_ended_ack", "conversation_id": "old-conv"}
