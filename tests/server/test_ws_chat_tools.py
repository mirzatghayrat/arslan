import pytest

from server.db.models import Spawn
from tests.server.conftest import build_ws_client


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
        async with maker() as s:
            from server.registry.seeder import seed_registry_with
            await seed_registry_with(s)
            s.add(Spawn(id=7, name="小美", domain_category="content", system_prompt="sp"))
            await s.commit()

    return build_ws_client(
        portal, tmp_path, monkeypatch, _seed,
        db_name="wc.db", env={"ARSLAN_API_TOKEN": ""},
    )


def test_direct_chat_emits_tool_frames(app_client, monkeypatch):
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
    with app_client.websocket_connect("/ws/chat/7?token=") as ws:
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
