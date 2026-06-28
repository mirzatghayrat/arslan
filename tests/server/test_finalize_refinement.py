import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

import server.db.session as db_session
from server.db.models import Base, Spawn, ArslanMessage


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'f.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        async with m() as s:
            s.add(Spawn(id=3, name="小美", domain_category="content", system_prompt="sp"))
            await s.commit()
    anyio.run(_seed)
    # Empty WS token: reload config so config.settings.api_token reflects the unset
    # env (auth reads config.settings, not the env var directly) — matches the sibling
    # WS tests' pattern and prevents token pollution from an earlier test in the suite.
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    import importlib
    import server.config as config
    importlib.reload(config)
    from server.main import app
    return app, m


def test_finalize_refinement_writes_deliverable_and_acks(client):
    app, m = client
    with TestClient(app).websocket_connect("/ws/arslan/conv-1?token=") as ws:
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
        async with m() as s:
            row = (await s.execute(select(ArslanMessage).where(ArslanMessage.id == new_id))).scalar_one()
            return row
    row = anyio.run(_check)
    assert row.display_content == "REFINED FINAL" and row.spawn_id == 3


def test_finalize_refinement_rejects_blank_content(client):
    app, _ = client
    with TestClient(app).websocket_connect("/ws/arslan/conv-2?token=") as ws:
        ws.send_json({"type": "finalize_refinement", "spawn_id": 3, "message_id": 1, "content": "  "})
        types = []
        for _ in range(6):
            f = ws.receive_json()
            types.append((f.get("type"), f.get("code")))
            if f.get("type") == "error":
                break
    assert any(t == ("error", "INVALID_INPUT") for t in types)
