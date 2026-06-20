"""Router proposal-awareness: NL confirm / refine / new for a pending proposal."""
import pytest
from server.orchestrator import arslan
from server.services import phase_service


async def _aw(v):
    return v


@pytest.mark.asyncio
async def test_nl_confirm_triggers_execute(monkeypatch):
    monkeypatch.setattr(phase_service, "get_pending", lambda c: _aw({"spawn_id": 4, "phase": "proposing", "direction": "d"}))
    called = {}

    async def fake_confirm(conversation_id, spawn_id, emit):
        called["yes"] = (conversation_id, spawn_id)

    monkeypatch.setattr(arslan, "confirm_and_execute", fake_confirm)
    monkeypatch.setattr(arslan, "_classify_followup", lambda msg, direction: _aw("confirm"))
    monkeypatch.setattr(arslan.memory, "add_message", lambda *a, **k: _aw(1))
    monkeypatch.setattr(arslan.memory, "maybe_compact", lambda *a, **k: _aw(None))
    await arslan.handle_user_message("conv-y", "好的就这样", lambda e: None)
    assert called.get("yes") == ("conv-y", 4)


@pytest.mark.asyncio
async def test_nl_refine_triggers_dispatch_propose(monkeypatch):
    monkeypatch.setattr(phase_service, "get_pending", lambda c: _aw({"spawn_id": 4, "phase": "proposing", "direction": "original direction"}))
    called = {}

    async def fake_dispatch(conv_id, spawn_id, task_brief, emit, *, mode="execute", prior_output=None, instruction=None):
        called["dispatch"] = {"conv_id": conv_id, "spawn_id": spawn_id, "mode": mode, "instruction": instruction}

    monkeypatch.setattr(arslan, "_dispatch_spawn", fake_dispatch)
    monkeypatch.setattr(arslan, "_classify_followup", lambda msg, direction: _aw("refine"))
    monkeypatch.setattr(arslan.memory, "add_message", lambda *a, **k: _aw(1))
    monkeypatch.setattr(arslan.memory, "maybe_compact", lambda *a, **k: _aw(None))
    await arslan.handle_user_message("conv-r", "make it shorter", lambda e: None)
    assert called.get("dispatch", {}).get("mode") == "propose"
    assert called["dispatch"]["conv_id"] == "conv-r"
    assert called["dispatch"]["spawn_id"] == 4
    assert called["dispatch"]["instruction"] == "make it shorter"


@pytest.mark.asyncio
async def test_nl_new_falls_through_to_router(monkeypatch):
    monkeypatch.setattr(phase_service, "get_pending", lambda c: _aw({"spawn_id": 4, "phase": "proposing", "direction": "d"}))
    monkeypatch.setattr(phase_service, "clear", lambda c, s: _aw(None))
    monkeypatch.setattr(arslan, "_classify_followup", lambda msg, direction: _aw("new"))

    router_called = {}

    from server.orchestrator import router as _router

    async def fake_route(conv, msg):
        router_called["yes"] = True
        return _router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", fake_route)
    monkeypatch.setattr(arslan.memory, "add_message", lambda *a, **k: _aw(1))
    monkeypatch.setattr(arslan.memory, "maybe_compact", lambda *a, **k: _aw(None))
    monkeypatch.setattr(arslan.memory, "save_facts", lambda *a, **k: _aw([]))
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: _aw(None))
    await arslan.handle_user_message("conv-n", "something else entirely", lambda e: None)
    assert router_called.get("yes") is True


@pytest.mark.asyncio
async def test_no_pending_does_not_call_classify(monkeypatch):
    monkeypatch.setattr(phase_service, "get_pending", lambda c: _aw(None))
    monkeypatch.setattr(arslan, "_classify_followup", lambda msg, direction: (_ for _ in ()).throw(AssertionError("should not be called")))

    from server.orchestrator import router as _router

    async def fake_route(conv, msg):
        return _router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", fake_route)
    monkeypatch.setattr(arslan.memory, "add_message", lambda *a, **k: _aw(1))
    monkeypatch.setattr(arslan.memory, "maybe_compact", lambda *a, **k: _aw(None))
    monkeypatch.setattr(arslan.memory, "save_facts", lambda *a, **k: _aw([]))
    monkeypatch.setattr(arslan, "_handle_answer", lambda *a, **k: _aw(None))
    # Should not raise
    await arslan.handle_user_message("conv-none", "hi", lambda e: None)


@pytest.mark.asyncio
async def test_classify_followup_defaults_to_new_on_bad_json(monkeypatch):
    """_classify_followup must return 'new' when the LLM returns invalid JSON."""
    class _BadAdapter:
        async def chat(self, system, user):
            class R:
                content = "not json at all"
            return R()

    async def _stub_build():
        return _BadAdapter()

    monkeypatch.setattr(arslan, "_build_classify_adapter", _stub_build)
    result = await arslan._classify_followup("some message", "some direction")
    assert result == "new"


@pytest.mark.asyncio
async def test_classify_followup_returns_confirm(monkeypatch):
    """_classify_followup correctly parses a confirm response."""
    class _GoodAdapter:
        async def chat(self, system, user):
            class R:
                content = '{"kind": "confirm"}'
            return R()

    async def _stub_build():
        return _GoodAdapter()

    monkeypatch.setattr(arslan, "_build_classify_adapter", _stub_build)
    result = await arslan._classify_followup("好的就这样", "write a blog post")
    assert result == "confirm"


@pytest.mark.asyncio
async def test_classify_followup_returns_refine(monkeypatch):
    """_classify_followup correctly parses a refine response."""
    class _GoodAdapter:
        async def chat(self, system, user):
            class R:
                content = '{"kind": "refine"}'
            return R()

    async def _stub_build():
        return _GoodAdapter()

    monkeypatch.setattr(arslan, "_build_classify_adapter", _stub_build)
    result = await arslan._classify_followup("make it shorter", "write a long essay")
    assert result == "refine"


@pytest.mark.asyncio
async def test_classify_followup_unknown_kind_defaults_to_new(monkeypatch):
    """_classify_followup returns 'new' for an unexpected kind value."""
    class _WeirdAdapter:
        async def chat(self, system, user):
            class R:
                content = '{"kind": "banana"}'
            return R()

    async def _stub_build():
        return _WeirdAdapter()

    monkeypatch.setattr(arslan, "_build_classify_adapter", _stub_build)
    result = await arslan._classify_followup("do something", "direction")
    assert result == "new"
