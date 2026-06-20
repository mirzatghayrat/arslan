import pytest
from server.orchestrator import arslan, router, dispatcher
from server.services import phase_service

async def _aw(v): return v

@pytest.mark.asyncio
async def test_open_task_proposes_and_sets_phase(monkeypatch):
    events = []
    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, mode="execute", **kw):
        events.append(("dispatch", mode))
        return {"full_output":"proposal text","spawn_name":"x","summary_message_id":1,
                "assistant_message_id":2,"escalation":None}
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)
    monkeypatch.setattr(dispatcher, "get_spawn_name", lambda i: _aw("x"))
    monkeypatch.setattr(phase_service, "set_proposing", lambda c,s,d: _aw(None))
    r = router.RouterResult(action="route", spawn_id=4, task_brief="help linkedin", needs_proposal=True)
    await arslan._handle_route("conv-x", r, events.append)
    assert ("dispatch","propose") in events
    assert any(isinstance(e, dict) and e.get("type") == "proposal" for e in events)

@pytest.mark.asyncio
async def test_crisp_task_executes_directly(monkeypatch):
    events = []
    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, mode="execute", **kw):
        events.append(("dispatch", mode))
        return {"full_output":"out","spawn_name":"x","summary_message_id":1,"assistant_message_id":2,"escalation":None}
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)
    monkeypatch.setattr(dispatcher, "get_spawn_name", lambda i: _aw("x"))
    r = router.RouterResult(action="route", spawn_id=4, task_brief="summarize this", needs_proposal=False)
    await arslan._handle_route("conv-y", r, events.append)
    assert ("dispatch","execute") in events
    assert not any(isinstance(e, dict) and e.get("type") == "proposal" for e in events)

@pytest.mark.asyncio
async def test_confirm_and_execute_dispatches_execute(monkeypatch):
    events = []
    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, mode="execute", **kw):
        events.append(("dispatch", mode, task_brief));
        return {"full_output":"out","spawn_name":"x","summary_message_id":1,"assistant_message_id":2,"escalation":None}
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)
    monkeypatch.setattr(dispatcher, "get_spawn_name", lambda i: _aw("x"))
    monkeypatch.setattr(phase_service, "get_pending", lambda c: _aw({"spawn_id":4,"phase":"proposing","direction":"the confirmed direction"}))
    monkeypatch.setattr(phase_service, "clear", lambda c,s=None: _aw(None))
    await arslan.confirm_and_execute("conv-z", 4, events.append)
    assert any(t[:2]==("dispatch","execute") and "the confirmed direction" in t[2] for t in events if isinstance(t, tuple))
