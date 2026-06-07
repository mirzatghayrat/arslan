"""End-to-end build dialogue over the WebSocket, using FastAPI's TestClient."""
import os

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib

    import server.config as config

    importlib.reload(config)

    # Point the WS handlers' session factory at an isolated temp DB.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'ws.db'}")

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    anyio.run(_create)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    return TestClient(create_app())


def test_build_dialogue_to_completion(app_client):
    with app_client.websocket_connect("/ws/build/sess-1") as ws:
        first = ws.receive_json()
        assert first["type"] == "question"
        assert first["node_id"] == "domain"

        # Answer each of the 5 nodes. Free-text answers drive keyword extraction.
        answers = [
            "I want a xiaohongshu beauty content creator",  # domain
            "content generation and q&a",                    # capabilities
            "a friendly senior beauty blogger",              # persona
            "web",                                           # runtime
            "beauty-guru",                                   # spawn_name
        ]
        last = first
        for ans in answers:
            ws.send_json({"type": "user_message", "content": ans})
            last = ws.receive_json()
            # Server may emit progress then question, or finally build_complete.
            while last["type"] == "progress":
                last = ws.receive_json()

        assert last["type"] == "build_complete"
        assert last["spawn_name"] == "beauty-guru"
        assert isinstance(last["spawn_id"], int)


def test_build_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "needed")
    import importlib

    import server.config as config

    importlib.reload(config)
    import server.auth as auth

    importlib.reload(auth)
    from server.main import create_app

    client = TestClient(create_app())
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/build/sess-x?token=wrong") as ws:
            ws.receive_json()
    # monkeypatch reverts ARSLAN_API_TOKEN; reload config/auth so later tests see it unset.
    importlib.reload(config)
    importlib.reload(auth)


def _drain_to_non_progress(ws):
    msg = ws.receive_json()
    while msg["type"] == "progress":
        msg = ws.receive_json()
    return msg


def test_build_resume_after_reconnect(app_client):
    # First connection: answer the domain node, then drop the socket.
    with app_client.websocket_connect("/ws/build/sess-resume") as ws:
        first = ws.receive_json()
        assert first["node_id"] == "domain"
        ws.send_json({"type": "user_message", "content": "xiaohongshu beauty creator"})
        nxt = _drain_to_non_progress(ws)
        assert nxt["type"] == "question"
        resumed_node = nxt["node_id"]  # the node we should resume at

    # Reconnect to the SAME session id: the server resends the current question.
    with app_client.websocket_connect("/ws/build/sess-resume") as ws2:
        resumed = ws2.receive_json()
        assert resumed["type"] == "question"
        assert resumed["node_id"] == resumed_node


def test_build_duplicate_name_is_deduplicated(app_client):
    answers_for = lambda name: [
        "xiaohongshu beauty creator",
        "content generation and q&a",
        "a friendly senior beauty blogger",
        "web",
        name,
    ]

    def run(session_id, name):
        with app_client.websocket_connect(f"/ws/build/{session_id}") as ws:
            ws.receive_json()  # initial domain question
            last = None
            for ans in answers_for(name):
                ws.send_json({"type": "user_message", "content": ans})
                last = _drain_to_non_progress(ws)
            return last

    first = run("dup-a", "dup")
    assert first["type"] == "build_complete"
    assert first["spawn_name"] == "dup"

    second = run("dup-b", "dup")
    assert second["type"] == "build_complete"
    assert second["spawn_name"] == "dup-2"  # auto-deduplicated
