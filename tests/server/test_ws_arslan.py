"""/ws/arslan endpoint: answer streaming, routing, suggest+confirm create."""
import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
import server.orchestrator.arslan as arslan_mod
from server.db.models import Base, Spawn


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'wsar.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            s.add(
                Spawn(
                    id=7,
                    name="beauty-guru",
                    domain_category="content-creator",
                    capabilities=["content-generation"],
                    system_prompt="You are a beauty expert.",
                )
            )
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    return TestClient(create_app())


def test_answer_turn_streams(app_client, monkeypatch):
    # Stub the orchestration loop to a deterministic answer.
    async def _fake_handle(conv, msg, emit):
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_chunk", "content": "Hello"})
        emit({"type": "stream_end", "message_id": 1})

    monkeypatch.setattr(arslan_mod, "handle_user_message", _fake_handle)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        hist = ws.receive_json()
        assert hist["type"] == "history"
        ws.send_json({"type": "user_message", "content": "hi"})
        assert ws.receive_json()["type"] == "stream_start"
        assert ws.receive_json() == {"type": "stream_chunk", "content": "Hello"}
        assert ws.receive_json()["type"] == "stream_end"


def test_confirm_create_makes_spawn(app_client):
    draft = {
        "name": "translator",
        "domain": "personal-assistant.translator",
        "capabilities": ["qa-interaction"],
        "persona_role": "translator",
        "persona_tone": "precise",
    }
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "confirm_create", "draft": draft})
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        assert created["spawn_name"] == "translator"

    async def _check():
        async with db_session.AsyncSessionLocal() as s:
            rows = (await s.execute(select(Spawn).where(Spawn.name == "translator"))).scalars().all()
            return rows

    assert len(anyio.run(_check)) == 1


def test_confirm_create_dedups_duplicate_name(app_client):
    # "beauty-guru" already exists (seeded). A second create must auto-suffix.
    draft = {
        "name": "beauty-guru",
        "domain": "content-creator.xiaohongshu",
        "capabilities": [],
        "persona_role": "blogger",
    }
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "confirm_create", "draft": draft})
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        assert created["spawn_name"] == "beauty-guru-2"
