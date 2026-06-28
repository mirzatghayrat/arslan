import anyio
import importlib
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

import server.config as config
import server.db.session as db_session
from server.db.models import Base


@pytest.fixture
def app(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'se.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    anyio.run(_init)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    importlib.reload(config)
    from server.main import app as a
    return a


def test_session_ended_triggers_distill_when_enabled(app, monkeypatch):
    import server.ws.arslan as wsmod
    called = {}
    async def fake_distill(cid):
        called["cid"] = cid
    monkeypatch.setattr(wsmod.distill_service, "distill_session", fake_distill)
    async def always_on(_s):
        return True
    monkeypatch.setattr(wsmod.settings_service, "distill_enabled", always_on)
    with TestClient(app).websocket_connect("/ws/arslan/conv-x?token=") as ws:
        ws.send_json({"type": "session_ended", "conversation_id": "old-conv"})
        for _ in range(8):
            f = ws.receive_json()
            if f.get("type") == "session_ended_ack":
                break
    anyio.run(anyio.sleep, 0.05)
    assert called.get("cid") == "old-conv"


def test_session_ended_skips_when_disabled(app, monkeypatch):
    import server.ws.arslan as wsmod
    called = {}
    async def fake_distill(cid):
        called["cid"] = cid
    monkeypatch.setattr(wsmod.distill_service, "distill_session", fake_distill)
    async def always_off(_s):
        return False
    monkeypatch.setattr(wsmod.settings_service, "distill_enabled", always_off)
    with TestClient(app).websocket_connect("/ws/arslan/conv-y?token=") as ws:
        ws.send_json({"type": "session_ended", "conversation_id": "old-conv"})
        for _ in range(8):
            f = ws.receive_json()
            if f.get("type") == "session_ended_ack":
                break
    assert "cid" not in called
