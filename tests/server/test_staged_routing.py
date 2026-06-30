import pytest
from server.orchestrator import arslan, router, dispatcher
from server.services import phase_service, roster_service

async def _aw(v): return v


@pytest.fixture(autouse=True)
def _stub_run_recorder(monkeypatch):
    """These unit tests don't set up a DB; stub the RunRecorder so _dispatch_spawn
    doesn't try to persist a Run (recording is covered by test_run_recording_integration)."""
    from server.services import run_recorder

    class _Rec:
        run_id = 0
        def tee(self, emit):
            return emit
        async def finalize(self, **kwargs):
            return 0

    async def _start(**kwargs):
        return _Rec()

    monkeypatch.setattr(run_recorder.RunRecorder, "start", staticmethod(_start))

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
    monkeypatch.setattr(roster_service, "join", lambda c, s, *, via: _aw(None))
    monkeypatch.setattr(roster_service, "list_roster", lambda c: _aw([]))
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
    monkeypatch.setattr(roster_service, "join", lambda c, s, *, via: _aw(None))
    monkeypatch.setattr(roster_service, "list_roster", lambda c: _aw([]))
    # Already a roster member → direct execute (no invite card gate).
    monkeypatch.setattr(roster_service, "is_member", lambda c, s: _aw(True))
    r = router.RouterResult(action="route", spawn_id=4, task_brief="summarize this", needs_proposal=False)
    await arslan._handle_route("conv-y", r, events.append)
    assert ("dispatch","execute") in events
    assert not any(isinstance(e, dict) and e.get("type") == "proposal" for e in events)

@pytest.mark.asyncio
async def test_confirm_and_execute_dispatches_execute_confirmed_with_proposed_direction(monkeypatch):
    events = []
    async def fake_dispatch(conversation_id, *, spawn_id, task_brief, mode="execute", prior_output=None, **kw):
        events.append(("dispatch", mode, task_brief, prior_output))
        return {"full_output":"out","spawn_name":"x","summary_message_id":1,"assistant_message_id":2,"escalation":None}
    monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)
    monkeypatch.setattr(dispatcher, "get_spawn_name", lambda i: _aw("x"))
    # the spawn's prior propose output (its proposed direction) must be carried into execute
    monkeypatch.setattr(dispatcher, "last_spawn_output", lambda i: _aw("the proposed direction text"))
    monkeypatch.setattr(phase_service, "get_pending", lambda c: _aw({"spawn_id":4,"phase":"proposing","direction":"the confirmed direction"}))
    monkeypatch.setattr(phase_service, "clear", lambda c,s=None: _aw(None))
    monkeypatch.setattr(roster_service, "join", lambda c, s, *, via: _aw(None))
    monkeypatch.setattr(roster_service, "list_roster", lambda c: _aw([]))
    await arslan.confirm_and_execute("conv-z", 4, events.append)
    rec = next(t for t in events if isinstance(t, tuple) and t[0] == "dispatch")
    assert rec[1] == "execute_confirmed"
    assert "the confirmed direction" in rec[2]
    assert rec[3] == "the proposed direction text"
