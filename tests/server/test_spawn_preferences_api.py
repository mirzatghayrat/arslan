import pytest

from server.db.models import Spawn
from tests.server.conftest import build_ws_client


@pytest.fixture
def client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
        async with maker() as s:
            s.add(Spawn(id=3, name="小美", domain_category="content", system_prompt="sp",
                        memory_facts=["输出更简短", "标注来源"]))
            await s.commit()
    return build_ws_client(portal, tmp_path, monkeypatch, _seed, db_name="p.db",
                           env={"ARSLAN_API_TOKEN": ""})


def test_get_preferences(client):
    r = client.get("/api/v1/spawns/3/preferences")
    assert r.status_code == 200 and r.json()["preferences"] == ["输出更简短", "标注来源"]


def test_delete_preference(client):
    r = client.request("DELETE", "/api/v1/spawns/3/preferences", json={"fact": "标注来源"})
    assert r.status_code == 200 and r.json()["preferences"] == ["输出更简短"]
    # deleting a non-existent fact is a no-op 200
    r2 = client.request("DELETE", "/api/v1/spawns/3/preferences", json={"fact": "不存在"})
    assert r2.status_code == 200 and r2.json()["preferences"] == ["输出更简短"]
