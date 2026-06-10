"""NL -> spawn draft inference."""
from __future__ import annotations

import json

import pytest

from server.services import spawn_drafter


class _FakeResp:
    def __init__(self, content):
        self.content = content


class _FakeAdapter:
    def __init__(self, content):
        self._c = content

    async def chat(self, *, system, user):
        return _FakeResp(self._c)


@pytest.fixture(autouse=True)
def _isolate_context(monkeypatch):
    """Keep these tests pure-unit: avoid DB access from registry/facts."""

    async def _registry():
        return "(no spawns yet)"

    async def _facts():
        return ""

    monkeypatch.setattr(spawn_drafter._router, "_spawn_registry", _registry)
    monkeypatch.setattr(spawn_drafter.memory, "facts_text", _facts)


@pytest.fixture
def stub_adapter(monkeypatch):
    def _install(payload: dict):
        monkeypatch.setattr(spawn_drafter, "_get_adapter", lambda: _FakeAdapter(json.dumps(payload)))
    return _install


async def test_draft_from_text_returns_freeform_domain(stub_adapter):
    stub_adapter({"name": "equity-researcher", "domain": "finance.equity-research",
                  "capabilities": ["research"], "persona_role": "analyst", "persona_tone": "rigorous",
                  "reason": "finance research"})
    draft = await spawn_drafter.draft_from_text("I want help analyzing stocks fundamentals")
    assert draft["domain"] == "finance.equity-research"
    assert draft["name"] == "equity-researcher"


async def test_draft_refinement_passes_previous(monkeypatch):
    captured = {}
    class _Cap:
        async def chat(self, *, system, user):
            captured["user"] = user
            class R: content = json.dumps({"name": "x", "domain": "finance.quant", "capabilities": []})
            return R()
    monkeypatch.setattr(spawn_drafter, "_get_adapter", lambda: _Cap())
    await spawn_drafter.draft_from_text("make it quant-focused", previous={"name": "x", "domain": "finance.equity-research"})
    assert "finance.equity-research" in captured["user"]


async def test_draft_defaults_on_sparse_response(stub_adapter):
    stub_adapter({})  # model returned nothing useful
    draft = await spawn_drafter.draft_from_text("something")
    assert draft["name"] and draft["domain"] and isinstance(draft["capabilities"], list)
