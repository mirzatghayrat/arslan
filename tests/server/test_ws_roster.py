"""Tests for T4: roster_update frame builder + roster_invite/roster_kick WS handlers + on-connect roster."""
import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn
from server.ws import protocol


# ---------------------------------------------------------------------------
# Unit test: roster_update frame builder
# ---------------------------------------------------------------------------

def test_roster_update_frame():
    f = protocol.roster_update([{"spawn_id": 4, "spawn_name": "x", "joined_via": "invited", "status": "idle"}])
    assert f["type"] == "roster_update"
    assert f["members"][0]["spawn_id"] == 4


def test_roster_update_frame_empty():
    f = protocol.roster_update([])
    assert f == {"type": "roster_update", "members": []}


# ---------------------------------------------------------------------------
# Fixture: mirrors staged_client from test_ws_staged.py exactly
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


# ---------------------------------------------------------------------------
# Integration tests: on-connect roster, invite, kick, bad invite
# ---------------------------------------------------------------------------

def test_on_connect_sends_roster(staged_client):
    """On connect: after history frame, server sends roster_update with members==[]."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        history = ws.receive_json()
        assert history["type"] == "history"
        roster = ws.receive_json()
        assert roster["type"] == "roster_update"
        assert roster["members"] == []


def test_roster_invite_adds_member(staged_client):
    """roster_invite with valid spawn_id → roster_event(joined) then roster_update with that member."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update (empty)
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event "joined"
        frame = ws.receive_json()
        assert frame["type"] == "roster_update"
        assert len(frame["members"]) == 1
        assert frame["members"][0]["spawn_id"] == 4


def test_roster_kick_removes_member(staged_client):
    """roster_kick after invite → roster_event(left) then roster_update with members==[]."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update (empty)
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event "joined"
        ws.receive_json()  # roster_update after invite
        ws.send_json({"type": "roster_kick", "spawn_id": 4})
        ws.receive_json()  # roster_event "left"
        frame = ws.receive_json()
        assert frame["type"] == "roster_update"
        assert frame["members"] == []


def test_roster_invite_bad_spawn_id_error(staged_client):
    """roster_invite with spawn_id=None → error INVALID_INPUT, socket stays open."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": None})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "INVALID_INPUT"
        # Socket still open — confirm by sending a valid invite
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event "joined"
        frame = ws.receive_json()
        assert frame["type"] == "roster_update"
        assert frame["members"][0]["spawn_id"] == 4


def test_roster_invite_emits_roster_event(staged_client):
    """roster_invite for a new spawn → roster_event(joined) then roster_update."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update (empty)
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        event = ws.receive_json()
        assert event["type"] == "roster_event"
        assert event["action"] == "joined"
        assert event["spawn_id"] == 4
        roster = ws.receive_json()
        assert roster["type"] == "roster_update"
        assert len(roster["members"]) == 1


def test_roster_invite_idempotent_no_second_event(staged_client):
    """Re-inviting a spawn already in the roster does NOT emit a second roster_event."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        # First invite — should get roster_event + roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        first_event = ws.receive_json()
        assert first_event["type"] == "roster_event"
        assert first_event["action"] == "joined"
        ws.receive_json()  # roster_update
        # Second invite (already a member) — should get ONLY roster_update, no roster_event
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        second = ws.receive_json()
        assert second["type"] == "roster_update", (
            "expected roster_update only on idempotent re-invite, got: " + second["type"]
        )


def test_roster_kick_emits_roster_event(staged_client):
    """roster_kick after invite → roster_event(left) then roster_update with empty members."""
    with staged_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "roster_invite", "spawn_id": 4})
        ws.receive_json()  # roster_event "joined"
        ws.receive_json()  # roster_update
        ws.send_json({"type": "roster_kick", "spawn_id": 4})
        event = ws.receive_json()
        assert event["type"] == "roster_event"
        assert event["action"] == "left"
        assert event["spawn_id"] == 4
        roster = ws.receive_json()
        assert roster["type"] == "roster_update"
        assert roster["members"] == []
