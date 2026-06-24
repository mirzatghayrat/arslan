"""Chat WebSocket: streaming, persistence, and resume."""
import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

import server.db.session as db_session
import server.ws.chat as chat_module
from server.db.models import Base, Spawn


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'chat.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            s.add(
                Spawn(
                    name="beauty-guru",
                    domain_category="content-creator",
                    domain_subcategory="xiaohongshu",
                    capabilities=["content-generation"],
                    system_prompt="You are a beauty expert.",
                )
            )
            await s.commit()

    anyio.run(_seed)

    # Point the WS handlers' session factory at the isolated temp DB.
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    # Stub the LLM so no network call happens; yield deterministic chunks.
    async def _fake_stream(self, system, user, history=None, tools=None, temperature=0.7):
        for token in ["Based ", "on ", "trends..."]:
            yield token

    monkeypatch.setattr(chat_module.LLMAdapter, "chat_stream", _fake_stream)

    from server.main import create_app

    return TestClient(create_app())


def test_chat_streams_and_persists(app_client):
    with app_client.websocket_connect("/ws/chat/1") as ws:
        # Server sends history first (empty), then waits.
        hello = ws.receive_json()
        assert hello["type"] in ("history", "ready")

        ws.send_json({"type": "user_message", "content": "What serums?"})

        start = ws.receive_json()
        assert start["type"] == "stream_start"
        collected = ""
        while True:
            frame = ws.receive_json()
            if frame["type"] == "stream_chunk":
                collected += frame["content"]
            elif frame["type"] == "stream_end":
                break
        assert collected == "Based on trends..."


def test_chat_resume_replays_missed(app_client):
    # First connection: produce one exchange.
    with app_client.websocket_connect("/ws/chat/1") as ws:
        ws.receive_json()  # history/ready
        ws.send_json({"type": "user_message", "content": "Hi"})
        while ws.receive_json()["type"] != "stream_end":
            pass

    # Second connection resumes from message_id 0 → replays both stored messages.
    with app_client.websocket_connect("/ws/chat/1") as ws:
        ws.receive_json()  # history/ready
        ws.send_json({"type": "resume", "last_message_id": 0})
        replayed = []
        # Expect at least the user + assistant messages replayed as "message" frames.
        for _ in range(2):
            frame = ws.receive_json()
            if frame["type"] == "message":
                replayed.append(frame)
        assert any(m["role"] == "assistant" for m in replayed)


def test_history_frame_uses_message_id_key(app_client):
    # Produce one stored exchange.
    with app_client.websocket_connect("/ws/chat/1") as ws:
        ws.receive_json()  # initial (empty) history
        ws.send_json({"type": "user_message", "content": "hello"})
        while ws.receive_json()["type"] != "stream_end":
            pass
    # Reconnect: the history frame should now list stored messages with message_id.
    with app_client.websocket_connect("/ws/chat/1") as ws:
        hist = ws.receive_json()
        assert hist["type"] == "history"
        assert len(hist["messages"]) >= 1
        for m in hist["messages"]:
            assert "message_id" in m
            assert "id" not in m
            assert "role" in m and "content" in m


def test_chat_missing_spawn_closes_4004(app_client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with app_client.websocket_connect("/ws/chat/999") as ws:
            ws.receive_json()
    assert exc_info.value.code == 4004


def test_chat_llm_error_emits_recoverable_error_frame(app_client, monkeypatch):
    # Override the stubbed stream so the LLM "fails" mid-turn.
    async def _boom(self, system, user, history=None, tools=None, temperature=0.7):
        raise RuntimeError("llm down")
        yield ""  # unreachable; makes this an async generator

    monkeypatch.setattr(chat_module.LLMAdapter, "chat_stream", _boom)

    with app_client.websocket_connect("/ws/chat/1") as ws:
        ws.receive_json()  # history frame
        ws.send_json({"type": "user_message", "content": "hi"})
        start = ws.receive_json()
        assert start["type"] == "stream_start"
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "LLM_ERROR"
        assert err["recoverable"] is True


def test_chat_injects_kb(app_client, monkeypatch):
    captured = {}
    async def _s(self, system, user, history=None, tools=None, temperature=0.7):
        captured["system"] = system; captured["user"] = user
        yield "ok"
    monkeypatch.setattr(chat_module.LLMAdapter, "chat_stream", _s)
    from server.services import knowledge
    async def fake_retrieve(spawn_id, query, *, k=5): return ["KB FACT: serum X is best"]
    monkeypatch.setattr(knowledge, "retrieve", fake_retrieve)
    with app_client.websocket_connect("/ws/chat/1") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "user_message", "content": "what serum?"})
        # drain to stream_end
        while ws.receive_json()["type"] != "stream_end":
            pass
    assert "KB FACT: serum X is best" in captured["system"]


def test_chat_uses_attached_context(app_client, monkeypatch):
    captured = {}
    async def _s(self, system, user, history=None, tools=None, temperature=0.7):
        captured["user"] = user
        yield "ok"
    monkeypatch.setattr(chat_module.LLMAdapter, "chat_stream", _s)
    with app_client.websocket_connect("/ws/chat/1") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "summarise",
                      "attached_context": "DOC: q3 revenue up 20%", "attached_names": ["q3.pdf"]})
        while ws.receive_json()["type"] != "stream_end":
            pass
    assert "DOC: q3 revenue up 20%" in captured["user"]


def test_chat_storage_intent_stores(app_client, monkeypatch):
    from server.services import storage_intent, ingest
    from server.services.storage_intent import StorageIntent
    async def fake_classify(msg, names, spawns): return StorageIntent(store=True, target=None)
    monkeypatch.setattr(storage_intent, "classify", fake_classify)
    seen = {}
    async def fake_ingest(spawn_id, source, text, *, compress=False):
        seen["spawn_id"] = spawn_id; seen["text"] = text; return 4
    monkeypatch.setattr(ingest, "ingest_text", fake_ingest)
    with app_client.websocket_connect("/ws/chat/1") as ws:
        ws.receive_json()  # history
        # 1) drop material (ephemeral) — classify returns store via fake, so this very msg stores;
        #    to isolate, first send with attachment + a benign msg won't help since fake always stores.
        ws.send_json({"type": "user_message", "content": "记住这份",
                      "attached_context": "MATERIAL BODY", "attached_names": ["doc.pdf"]})
        frame = ws.receive_json()
        assert frame["type"] == "attachment_stored"
        assert frame["chunks"] == 4
    assert seen["spawn_id"] == 1
    assert seen["text"] == "MATERIAL BODY"


def test_chat_no_store_when_intent_false(app_client, monkeypatch):
    from server.services import storage_intent, ingest
    from server.services.storage_intent import StorageIntent
    async def fake_classify(msg, names, spawns): return StorageIntent(store=False, target=None)
    monkeypatch.setattr(storage_intent, "classify", fake_classify)
    called = {"ingest": False}
    async def fake_ingest(*a, **k): called["ingest"] = True; return 1
    monkeypatch.setattr(ingest, "ingest_text", fake_ingest)
    async def _s(self, system, user, history=None, tools=None, temperature=0.7):
        yield "reply"
    monkeypatch.setattr(chat_module.LLMAdapter, "chat_stream", _s)
    with app_client.websocket_connect("/ws/chat/1") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "what's in this?",
                      "attached_context": "MATERIAL", "attached_names": ["d.pdf"]})
        # should get a normal stream, NOT attachment_stored
        f = ws.receive_json()
        assert f["type"] == "stream_start"
        while ws.receive_json()["type"] != "stream_end":
            pass
    assert called["ingest"] is False
