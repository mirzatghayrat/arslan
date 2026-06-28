import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

import server.db.session as db_session
from server.db.models import Base, Spawn


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'p.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            s.add(Spawn(id=3, name="小美", domain_category="content", system_prompt="sp",
                        memory_facts=["输出更简短", "标注来源"]))
            await s.commit()
    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    from server.main import app
    return TestClient(app)


def test_get_preferences(client):
    r = client.get("/api/v1/spawns/3/preferences")
    assert r.status_code == 200 and r.json()["preferences"] == ["输出更简短", "标注来源"]


def test_delete_preference(client):
    r = client.request("DELETE", "/api/v1/spawns/3/preferences", json={"fact": "标注来源"})
    assert r.status_code == 200 and r.json()["preferences"] == ["输出更简短"]
    # deleting a non-existent fact is a no-op 200
    r2 = client.request("DELETE", "/api/v1/spawns/3/preferences", json={"fact": "不存在"})
    assert r2.status_code == 200 and r2.json()["preferences"] == ["输出更简短"]
