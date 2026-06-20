"""Router: needs_proposal flag (crisp-execute vs open-propose)."""
import pytest

from server.orchestrator import router


class _StubAdapter:
    def __init__(self, content):
        self._c = content

    async def chat(self, system, user):
        class R:
            content = self._c

        return R()


async def _async_str(s):
    return s


@pytest.mark.asyncio
async def test_route_carries_needs_proposal(monkeypatch):
    monkeypatch.setattr(router, "_get_adapter", lambda: _StubAdapter(
        '{"action":"route","spawn_id":4,"task_brief":"optimize headline","needs_proposal":true,"reason":"open"}'
    ))
    monkeypatch.setattr(router, "_spawn_registry", lambda: _async_str("- id=4 name=x domain=finance"))
    monkeypatch.setattr(
        router.memory, "assemble_working_context", lambda conv_id: _async_str({"summary": "", "history": []})
    )
    monkeypatch.setattr(router.memory, "facts_text", lambda: _async_str(""))
    monkeypatch.setattr(router, "_persist", lambda *a, **kw: _async_str(None))
    r = await router.route("conv-t1", "help with my linkedin")
    assert r.action == "route"
    assert r.needs_proposal is True


@pytest.mark.asyncio
async def test_route_needs_proposal_false_by_default(monkeypatch):
    monkeypatch.setattr(router, "_get_adapter", lambda: _StubAdapter(
        '{"action":"route","spawn_id":4,"task_brief":"summarize this article: X","reason":"crisp"}'
    ))
    monkeypatch.setattr(router, "_spawn_registry", lambda: _async_str("- id=4 name=x domain=content"))
    monkeypatch.setattr(
        router.memory, "assemble_working_context", lambda conv_id: _async_str({"summary": "", "history": []})
    )
    monkeypatch.setattr(router.memory, "facts_text", lambda: _async_str(""))
    monkeypatch.setattr(router, "_persist", lambda *a, **kw: _async_str(None))
    r = await router.route("conv-t2", "summarize this article: X")
    assert r.action == "route"
    assert r.needs_proposal is False
