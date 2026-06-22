import pytest
from server.orchestrator import arslan, dispatcher
from server.services import roster_service

async def _aw(v): return v

@pytest.mark.asyncio
async def test_dispatch_autojoins_roster(monkeypatch):
    joined = []
    async def fake_join(conversation_id, spawn_id, *, via): joined.append((conversation_id, spawn_id, via))
    async def fake_list(conversation_id): return []
    monkeypatch.setattr(roster_service, "join", fake_join)
    monkeypatch.setattr(roster_service, "list_roster", fake_list)
    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, **kw):
        return {"full_output":"o","spawn_name":"x","summary_message_id":1,"assistant_message_id":2,"escalation":None}
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)
    monkeypatch.setattr(dispatcher, "get_spawn_name", lambda i: _aw("x"))
    frames = []
    await arslan._dispatch_spawn("conv-a", 4, "do it", frames.append)
    assert ("conv-a", 4, "routed") in joined
    assert any(isinstance(f, dict) and f.get("type") == "roster_update" for f in frames)
