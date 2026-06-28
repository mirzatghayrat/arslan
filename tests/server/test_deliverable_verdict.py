"""Tests for T7.5: accept_deliverable / discard WS handlers wired to evolution_service."""
from __future__ import annotations

from datetime import datetime, timedelta

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
import server.orchestrator.arslan as arslan_mod
from server.db.models import ArslanMessage, Base, Spawn
from server.services import evolution_service


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_engine_and_maker(tmp_path, db_name="verdict.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / db_name}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, maker


@pytest.fixture
def verdict_db(tmp_path, monkeypatch):
    """In-memory SQLite DB seeded with a spawn, a prior user message, and a deliverable."""
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib
    import server.config as config
    importlib.reload(config)

    engine, maker = _make_engine_and_maker(tmp_path, "verdict_unit.db")

    CONVERSATION_ID = "conv-test-1"
    # Timestamp ~2s ago so elapsed is measurable
    deliverable_ts = datetime.utcnow() - timedelta(seconds=2)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            s.add(Spawn(
                id=7,
                name="TestSpawn",
                domain_category="test",
                capabilities=[],
                system_prompt="You are a test spawn.",
            ))
            # Prior user message (id=1)
            s.add(ArslanMessage(
                id=1,
                conversation_id=CONVERSATION_ID,
                role="user",
                content="write me a poem",
                timestamp=datetime.utcnow() - timedelta(seconds=10),
            ))
            # Deliverable spawn summary (id=2)
            s.add(ArslanMessage(
                id=2,
                conversation_id=CONVERSATION_ID,
                role="spawn_summary",
                content="[summary]",
                display_content="Roses are red, violets are blue.",
                spawn_id=7,
                timestamp=deliverable_ts,
            ))
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return CONVERSATION_ID


# ---------------------------------------------------------------------------
# Unit test: record_deliverable_verdict
# ---------------------------------------------------------------------------

def test_record_deliverable_verdict_accept(verdict_db, monkeypatch, tmp_path):
    """record_deliverable_verdict must call record_verdict with correct args and emit ack."""
    conversation_id = verdict_db
    captured = {}

    def fake_record_verdict(spawn_name, *, session_id, user_input, agent_output, action, elapsed_seconds, **kw):
        captured.update(
            spawn_name=spawn_name,
            session_id=session_id,
            user_input=user_input,
            agent_output=agent_output,
            action=action,
            elapsed_seconds=elapsed_seconds,
        )

    monkeypatch.setattr(evolution_service, "record_verdict", fake_record_verdict)

    emitted = []

    def emit(ev):
        emitted.append(ev)

    async def _run():
        await arslan_mod.record_deliverable_verdict(
            conversation_id, spawn_id=7, action="accept", message_id=2, emit=emit
        )

    anyio.run(_run)

    assert captured["action"] == "accept"
    assert captured["agent_output"] == "Roses are red, violets are blue."
    assert captured["session_id"] == conversation_id
    assert captured["user_input"] == "write me a poem"
    assert isinstance(captured["elapsed_seconds"], float)
    assert captured["elapsed_seconds"] >= 0.0

    # Should have emitted exactly one verdict_recorded ack
    acks = [e for e in emitted if e.get("type") == "verdict_recorded"]
    assert len(acks) == 1
    assert acks[0]["spawn_id"] == 7
    assert acks[0]["action"] == "accept"


def test_record_deliverable_verdict_persists_feedback_row(verdict_db, monkeypatch):
    """A verdict must also persist a per-conversation Feedback DB row (keyed by the real
    conversation_id, action mapped to thumbs vocabulary) so session-end distillation can
    read 👍/👎 as a signal."""
    from server.db.models import Feedback

    conversation_id = verdict_db
    monkeypatch.setattr(evolution_service, "record_verdict", lambda *a, **kw: None)

    async def _run():
        await arslan_mod.record_deliverable_verdict(
            conversation_id, spawn_id=7, action="accept", message_id=2, emit=lambda e: None
        )
        async with db_session.AsyncSessionLocal() as s:
            return (await s.execute(select(Feedback).where(Feedback.spawn_id == 7))).scalars().all()

    rows = anyio.run(_run)
    assert len(rows) == 1
    assert rows[0].session_id == conversation_id
    assert rows[0].user_action == "thumbs_up"
    assert rows[0].quality_signal == 1


def test_record_deliverable_verdict_discard_persists_thumbs_down(verdict_db, monkeypatch):
    """A discard verdict persists a thumbs_down Feedback row with quality_signal -1."""
    from server.db.models import Feedback

    conversation_id = verdict_db
    monkeypatch.setattr(evolution_service, "record_verdict", lambda *a, **kw: None)

    async def _run():
        await arslan_mod.record_deliverable_verdict(
            conversation_id, spawn_id=7, action="discard", message_id=2, emit=lambda e: None
        )
        async with db_session.AsyncSessionLocal() as s:
            return (await s.execute(select(Feedback).where(Feedback.spawn_id == 7))).scalars().all()

    rows = anyio.run(_run)
    assert len(rows) == 1
    assert rows[0].user_action == "thumbs_down"
    assert rows[0].quality_signal == -1


def test_record_deliverable_verdict_missing_message(verdict_db, monkeypatch):
    """When message_id is None, elapsed defaults to large value and agent_output is empty."""
    conversation_id = verdict_db
    captured = {}

    def fake_record_verdict(spawn_name, *, session_id, user_input, agent_output, action, elapsed_seconds, **kw):
        captured.update(elapsed_seconds=elapsed_seconds, agent_output=agent_output)

    monkeypatch.setattr(evolution_service, "record_verdict", fake_record_verdict)

    emitted = []

    async def _run():
        await arslan_mod.record_deliverable_verdict(
            conversation_id, spawn_id=7, action="discard", message_id=None, emit=emitted.append
        )

    anyio.run(_run)

    assert captured["elapsed_seconds"] == 999.0  # _MISSING_ELAPSED_SECONDS sentinel
    assert captured["agent_output"] == ""
    acks = [e for e in emitted if e.get("type") == "verdict_recorded"]
    assert acks[0]["action"] == "discard"


def test_record_deliverable_verdict_leveling_failure_does_not_raise(verdict_db, monkeypatch):
    """A leveling failure must not propagate — the ack must still be emitted."""
    conversation_id = verdict_db

    def boom(*a, **kw):
        raise RuntimeError("DB exploded")

    monkeypatch.setattr(evolution_service, "record_verdict", boom)

    emitted = []

    async def _run():
        await arslan_mod.record_deliverable_verdict(
            conversation_id, spawn_id=7, action="accept", message_id=2, emit=emitted.append
        )

    anyio.run(_run)  # must not raise

    acks = [e for e in emitted if e.get("type") == "verdict_recorded"]
    assert len(acks) == 1


def test_record_deliverable_verdict_unknown_spawn_emits_error(verdict_db, monkeypatch):
    """An unknown spawn_id (get_spawn_name returns None) must emit an error frame and
    must NOT call record_verdict."""
    conversation_id = verdict_db
    record_called = []

    monkeypatch.setattr(evolution_service, "record_verdict", lambda *a, **kw: record_called.append(1))

    from server.orchestrator import dispatcher as disp_mod
    monkeypatch.setattr(disp_mod, "get_spawn_name", lambda *a, **kw: None)
    # dispatcher.get_spawn_name is async — patch with async version
    async def _fake_get_spawn_name(spawn_id):
        return None
    monkeypatch.setattr(disp_mod, "get_spawn_name", _fake_get_spawn_name)

    emitted = []

    async def _run():
        await arslan_mod.record_deliverable_verdict(
            conversation_id, spawn_id=9999, action="accept", message_id=None, emit=emitted.append
        )

    anyio.run(_run)

    assert record_called == [], "record_verdict must NOT be called for unknown spawn"
    errors = [e for e in emitted if e.get("type") == "error"]
    assert len(errors) == 1
    assert errors[0]["code"] == "INVALID_INPUT"
    assert errors[0]["recoverable"] is True
    # No verdict_recorded ack
    acks = [e for e in emitted if e.get("type") == "verdict_recorded"]
    assert acks == []


# ---------------------------------------------------------------------------
# WS integration tests: accept_deliverable + discard handlers
# ---------------------------------------------------------------------------

@pytest.fixture
def verdict_client(tmp_path, monkeypatch):
    """TestClient fixture matching staged_client style from test_ws_staged.py."""
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib
    import server.config as config
    importlib.reload(config)

    engine, maker = _make_engine_and_maker(tmp_path, "verdict_ws.db")

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            s.add(Spawn(
                id=4,
                name="领英智囊",
                domain_category="social-media",
                capabilities=["content-generation"],
                system_prompt="You are a LinkedIn advisor.",
            ))
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app
    return TestClient(create_app())


def test_accept_deliverable_calls_record_verdict(verdict_client, monkeypatch):
    """accept_deliverable WS frame must invoke record_deliverable_verdict with action='accept'."""
    calls = []

    async def _fake_record(conversation_id, spawn_id, action, message_id, emit):
        calls.append({"conversation_id": conversation_id, "spawn_id": spawn_id,
                       "action": action, "message_id": message_id})
        emit({"type": "verdict_recorded", "spawn_id": spawn_id, "action": action})

    monkeypatch.setattr(arslan_mod, "record_deliverable_verdict", _fake_record)

    with verdict_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "accept_deliverable", "spawn_id": 4, "message_id": 1})
        # Drain until verdict_recorded ack
        ack = None
        for _ in range(10):
            f = ws.receive_json()
            if f.get("type") == "verdict_recorded":
                ack = f
                break

    assert len(calls) == 1
    assert calls[0]["spawn_id"] == 4
    assert calls[0]["action"] == "accept"
    assert calls[0]["message_id"] == 1
    assert ack is not None
    assert ack["action"] == "accept"


def test_discard_calls_record_verdict(verdict_client, monkeypatch):
    """discard WS frame must invoke record_deliverable_verdict with action='discard'."""
    calls = []

    async def _fake_record(conversation_id, spawn_id, action, message_id, emit):
        calls.append({"action": action, "spawn_id": spawn_id})
        emit({"type": "verdict_recorded", "spawn_id": spawn_id, "action": action})

    monkeypatch.setattr(arslan_mod, "record_deliverable_verdict", _fake_record)

    with verdict_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "discard", "spawn_id": 4, "message_id": 2})
        ack = None
        for _ in range(10):
            f = ws.receive_json()
            if f.get("type") == "verdict_recorded":
                ack = f
                break

    assert len(calls) == 1
    assert calls[0]["action"] == "discard"
    assert ack is not None


def test_accept_deliverable_bad_spawn_id(verdict_client, monkeypatch):
    """accept_deliverable with missing spawn_id must send INVALID_INPUT and keep socket open."""
    calls = []

    async def _fake_record(conversation_id, spawn_id, action, message_id, emit):
        calls.append(spawn_id)
        emit({"type": "verdict_recorded", "spawn_id": spawn_id, "action": action})

    monkeypatch.setattr(arslan_mod, "record_deliverable_verdict", _fake_record)

    with verdict_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "accept_deliverable", "spawn_id": None})
        # drain the on-connect roster_update broadcast, then assert the error
        err = None
        for _ in range(10):
            f = ws.receive_json()
            if f.get("type") == "error":
                err = f
                break
        assert err is not None
        assert err["code"] == "INVALID_INPUT"
        # Socket still open — send valid message
        ws.send_json({"type": "accept_deliverable", "spawn_id": 4, "message_id": 1})
        for _ in range(10):
            f = ws.receive_json()
            if f.get("type") == "verdict_recorded":
                break

    assert 4 in calls
