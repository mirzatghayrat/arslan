import pytest
from sqlalchemy import select

from server.db.models import Spawn, ArslanMessage
from tests.server.conftest import build_ws_client


@pytest.fixture
def client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
        async with maker() as s:
            s.add(Spawn(id=3, name="小美", domain_category="content", system_prompt="sp"))
            await s.commit()

    return build_ws_client(
        portal, tmp_path, monkeypatch, _seed, db_name="f.db",
        env={"ARSLAN_API_TOKEN": ""},
    )


def test_finalize_refinement_writes_deliverable_and_acks(client):
    with client.websocket_connect("/ws/arslan/conv-1?token=") as ws:
        # drain any connect frames (roster_update etc.) then send
        ws.send_json({"type": "finalize_refinement", "spawn_id": 3, "message_id": 99, "content": "REFINED FINAL"})
        seen = []
        for _ in range(8):
            f = ws.receive_json()
            seen.append(f.get("type"))
            if f.get("type") == "deliverable_finalized":
                assert f["content"] == "REFINED FINAL"
                assert f["spawn_id"] == 3
                assert f["refined_from"] == 99
                new_id = f["message_id"]
            if "verdict_recorded" in seen and "deliverable_finalized" in seen:
                break
    assert "deliverable_finalized" in seen and "verdict_recorded" in seen

    async def _check():
        async with client.db_maker() as s:
            row = (await s.execute(select(ArslanMessage).where(ArslanMessage.id == new_id))).scalar_one()
            return row
    row = client.portal.call(_check)
    assert row.display_content == "REFINED FINAL" and row.spawn_id == 3


def test_finalize_refinement_rejects_blank_content(client):
    with client.websocket_connect("/ws/arslan/conv-2?token=") as ws:
        ws.send_json({"type": "finalize_refinement", "spawn_id": 3, "message_id": 1, "content": "  "})
        types = []
        for _ in range(6):
            f = ws.receive_json()
            types.append((f.get("type"), f.get("code")))
            if f.get("type") == "error":
                break
    assert any(t == ("error", "INVALID_INPUT") for t in types)
