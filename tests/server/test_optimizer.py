import pytest

from arslan.models import LLMResponse
from server.services import optimizer


class _Spawn:
    name = "小美"
    system_prompt = "You are a beauty blogger."
    persona_role = "beauty blogger"
    persona_tone = "friendly"


_ITEMS = [{
    "run_id": 1, "task": "写文案", "baseline_output": "原文案",
    "baseline_overall": 6.0,
    "baseline_dims": {"completion": {"status": "warn", "score": 5.0}},
}]


async def test_propose_returns_candidate(monkeypatch):
    class _A:
        async def chat(self, system, user):
            return LLMResponse(content="REVISED SYSTEM PROMPT", usage={})
    async def fake_build(role=None):
        return _A()
    monkeypatch.setattr(optimizer, "build_adapter", fake_build)

    out = await optimizer.propose(_Spawn(), _ITEMS)
    assert out == "REVISED SYSTEM PROMPT"


async def test_propose_falls_back_to_original_on_failure(monkeypatch):
    class _A:
        async def chat(self, system, user):
            raise RuntimeError("llm down")
    async def fake_build(role=None):
        return _A()
    monkeypatch.setattr(optimizer, "build_adapter", fake_build)

    out = await optimizer.propose(_Spawn(), _ITEMS)
    assert out == "You are a beauty blogger."


async def test_propose_falls_back_on_empty(monkeypatch):
    class _A:
        async def chat(self, system, user):
            return LLMResponse(content="   ", usage={})
    async def fake_build(role=None):
        return _A()
    monkeypatch.setattr(optimizer, "build_adapter", fake_build)
    assert await optimizer.propose(_Spawn(), _ITEMS) == "You are a beauty blogger."
