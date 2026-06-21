"""Tests for T6 gate-side additions: proposal frame builder + confirm_direction handler."""
import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
import server.orchestrator.arslan as arslan_mod
from server.db.models import Base, Spawn
from server.ws import protocol


# ---------------------------------------------------------------------------
# Unit test: proposal frame builder
# ---------------------------------------------------------------------------

def test_proposal_frame():
    f = protocol.proposal(4, "领英智囊")
    assert f == {"type": "proposal", "spawn_id": 4, "spawn_name": "领英智囊"}


def test_proposal_frame_none_name():
    f = protocol.proposal(99, None)
    assert f == {"type": "proposal", "spawn_id": 99, "spawn_name": None}


# ---------------------------------------------------------------------------
# Integration test: confirm_direction WS handler
# ---------------------------------------------------------------------------

@pytest.fixture
def staged_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'staged.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            s.add(
                Spawn(
                    id=4,
                    name="领英智囊",
                    domain_category="social-media",
                    capabilities=["content-generation"],
                    system_prompt="You are a LinkedIn advisor.",
                )
            )
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    return TestClient(create_app())


def test_confirm_direction_calls_confirm_and_execute(staged_client, monkeypatch):
    """confirm_direction WS message must invoke arslan.confirm_and_execute."""
    calls = []

    async def _fake_confirm_and_execute(conversation_id, spawn_id, emit):
        calls.append({"conversation_id": conversation_id, "spawn_id": spawn_id})
        emit({"type": "stream_end", "message_id": 0})

    monkeypatch.setattr(arslan_mod, "confirm_and_execute", _fake_confirm_and_execute)

    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_direction", "spawn_id": 4})
        # Drain until stream_end so we know the handler finished
        for _ in range(10):
            f = ws.receive_json()
            if f.get("type") == "stream_end":
                break

    assert len(calls) == 1
    assert calls[0]["spawn_id"] == 4


def test_confirm_direction_bad_spawn_id_recoverable(staged_client, monkeypatch):
    """confirm_direction with missing/bad spawn_id must send INVALID_INPUT and keep socket open."""
    calls = []

    async def _fake_confirm_and_execute(conversation_id, spawn_id, emit):
        calls.append(spawn_id)
        emit({"type": "stream_end", "message_id": 0})

    monkeypatch.setattr(arslan_mod, "confirm_and_execute", _fake_confirm_and_execute)

    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_direction", "spawn_id": None})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "INVALID_INPUT"
        # Socket still usable — send a valid confirm_direction to prove it
        ws.send_json({"type": "confirm_direction", "spawn_id": 4})
        # Drain until stream_end
        for _ in range(10):
            f = ws.receive_json()
            if f.get("type") == "stream_end":
                break

    # The second call (with valid spawn_id) must have gone through
    assert 4 in calls
