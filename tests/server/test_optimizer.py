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


# ── propose_edits tests ──────────────────────────────────────────────────────

import anyio


class _Resp:
    def __init__(self, content): self.content = content


class _Adapter:
    def __init__(self, content): self._c = content
    async def chat(self, *, system, user): return _Resp(self._c)


class _SpawnEdits:
    name = "fin"; persona_role = "analyst"; persona_tone = "terse"
    system_prompt = "## Role\nYou are an analyst."


def _items():
    return [{"task": "summarize", "baseline_overall": 6,
             "baseline_dims": {"completion": {"score": 6, "status": "weak"}}}]


def test_propose_edits_parses_and_caps(monkeypatch):
    content = ('{"edits": ['
               '{"op":"replace","section":"Role","content":"You are a sharp analyst."},'
               '{"op":"add","section":"Style","content":"Lead with the number."},'
               '{"op":"add","section":"Extra","content":"third"}]}')

    async def fake_build(role): return _Adapter(content)
    monkeypatch.setattr(optimizer, "build_adapter", fake_build)
    edits = anyio.run(lambda: optimizer.propose_edits(_SpawnEdits(), _items(), lr_budget=2, avoid=[]))
    assert len(edits) == 2  # capped to lr_budget
    assert edits[0]["op"] == "replace" and edits[0]["section"] == "Role"


def test_propose_edits_drops_avoided(monkeypatch):
    content = ('{"edits": ['
               '{"op":"add","section":"Style","content":"Lead with the number."}]}')

    async def fake_build(role): return _Adapter(content)
    monkeypatch.setattr(optimizer, "build_adapter", fake_build)
    avoid = [{"op": "add", "section": "Style", "content": "Lead with the number."}]
    edits = anyio.run(lambda: optimizer.propose_edits(_SpawnEdits(), _items(), lr_budget=2, avoid=avoid))
    assert edits == []  # the only proposed edit was in the avoid buffer


def test_propose_edits_empty_on_failure(monkeypatch):
    class _Boom:
        async def chat(self, *, system, user): raise RuntimeError("llm down")

    async def fake_build(role): return _Boom()
    monkeypatch.setattr(optimizer, "build_adapter", fake_build)
    edits = anyio.run(lambda: optimizer.propose_edits(_SpawnEdits(), _items(), lr_budget=2, avoid=[]))
    assert edits == []
