import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

import server.db.session as db_session
from server.db.models import Base, Spawn


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'wc.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        from server.registry.seeder import seed_registry
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        await seed_registry()
        async with m() as s:
            s.add(Spawn(id=7, name="小美", domain_category="content", system_prompt="sp"))
            await s.commit()
    anyio.run(_seed)
    monkeypatch.setenv("ARSLAN_API_TOKEN", "")
    from server.main import app
    return app, monkeypatch


def test_direct_chat_emits_tool_frames(client):
    app, monkeypatch = client
    from server.orchestrator import spawn_loop

    async def fake_run(*, spawn_id, system, user_content, history, current_turn, emit, on_chunk, allow_escalation):
        assert allow_escalation is False
        assert "web_search" in system           # equipment block reached the spawn
        emit({"type": "tool_call", "tool": "web_search", "args_summary": '{"query":"x"}'})
        emit({"type": "tool_result", "tool": "web_search", "ok": True, "summary": "found",
              "artifact": None})
        emit({"type": "tool_call", "tool": "render_chart", "args_summary": "{}"})
        emit({"type": "tool_result", "tool": "render_chart", "ok": True, "summary": "chart",
              "artifact": {"kind": "svg", "content": "<svg/>"}})
        on_chunk("Here is your chart.")
        return {"final": "Here is your chart.", "escalation": None, "tool_trace": []}

    monkeypatch.setattr(spawn_loop, "run", fake_run)
    with TestClient(app).websocket_connect("/ws/chat/7?token=") as ws:
        ws.receive_json()  # history frame
        ws.send_json({"type": "user_message", "content": "chart AAPL"})
        frames = []
        while True:
            f = ws.receive_json()
            frames.append(f)
            if f["type"] == "stream_end":
                break
    types = [f["type"] for f in frames]
    assert "tool_call" in types and "tool_result" in types
    assert "stream_chunk" in types and "stream_end" in types
    tr = next(f for f in frames if f["type"] == "tool_result" and f["tool"] == "render_chart")
    assert tr["artifact"]["content"] == "<svg/>"
