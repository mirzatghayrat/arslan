"""Sandbox WS: in-memory session, confirm_merge merges to main, discard is a no-op."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from server.db.models import ArslanMessage, Spawn
from tests.server.conftest import build_ws_client


@pytest.fixture
def sandbox_client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
        async with maker() as s:
            s.add(Spawn(id=5, name="Mermer", domain_category="personal-assistant",
                        capabilities=[], system_prompt="You are Mermer.", memory_facts=[]))
            await s.commit()

    # Stub the LLM turn so the WS test never calls a real provider.
    from server.orchestrator import spawn_loop
    async def fake_run(*, spawn_id, system, user_content, history, current_turn, emit, on_chunk, allow_escalation=True):
        on_chunk("精简版周报")
        return {"final": "精简版周报"}
    monkeypatch.setattr(spawn_loop, "run", fake_run)
    from server.services import sandbox_service
    async def fake_summary(name, content):
        return "精简版周报"
    monkeypatch.setattr(sandbox_service, "summarize_deliverable", fake_summary)
    from server.services import distill_service
    async def fake_distill(spawn_id, signals):
        return None
    monkeypatch.setattr(distill_service, "distill_from_signals", fake_distill)

    return build_ws_client(portal, tmp_path, monkeypatch, _seed, db_name="sandbox.db",
                           env={"ARSLAN_API_TOKEN": ""})  # disable WS token gate in tests


def _read_until(ws, type_, limit=20):
    for _ in range(limit):
        f = ws.receive_json()
        if f.get("type") == type_:
            return f
    return None


def test_sandbox_confirm_merges_to_main(sandbox_client, monkeypatch):
    from server.services import evolution_service
    monkeypatch.setattr(evolution_service, "record_verdict", lambda *a, **k: None)

    with sandbox_client.websocket_connect("/ws/sandbox/5") as ws:
        ws.receive_json()  # history (empty)
        ws.send_json({"type": "user_message", "content": "把开头改紧凑"})
        assert _read_until(ws, "stream_end") is not None
        ws.send_json({"type": "confirm_merge", "conversation_id": "main"})
        merged = _read_until(ws, "merged")
        assert merged is not None

    async def _check():
        async with sandbox_client.db_maker() as s:
            return (await s.execute(select(ArslanMessage).where(
                ArslanMessage.role == "spawn_summary", ArslanMessage.conversation_id == "main"))).scalars().all()
    rows = sandbox_client.portal.call(_check)
    assert len(rows) == 1
    assert "精简版周报" in rows[0].display_content


def test_sandbox_confirm_merge_failure_emits_error_not_merged(sandbox_client, monkeypatch):
    """If confirm_sandbox_merge returns None (spawn vanished mid-session), the WS must
    emit an error and NOT a `merged` frame with a null message id."""
    import server.orchestrator.arslan as arslan_mod
    async def fake_merge(*a, **k):
        return None
    monkeypatch.setattr(arslan_mod, "confirm_sandbox_merge", fake_merge)

    with sandbox_client.websocket_connect("/ws/sandbox/5") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "user_message", "content": "草稿"})
        assert _read_until(ws, "stream_end") is not None
        ws.send_json({"type": "confirm_merge", "conversation_id": "main"})
        assert _read_until(ws, "error") is not None


def test_sandbox_discard_writes_nothing(sandbox_client):
    with sandbox_client.websocket_connect("/ws/sandbox/5") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "user_message", "content": "草稿"})
        assert _read_until(ws, "stream_end") is not None
        ws.send_json({"type": "discard"})
        assert _read_until(ws, "discarded") is not None

    async def _check():
        async with sandbox_client.db_maker() as s:
            return (await s.execute(select(ArslanMessage).where(
                ArslanMessage.role == "spawn_summary"))).scalars().all()
    assert sandbox_client.portal.call(_check) == []
