"""K1: with ARSLAN_TOOL_PROTOCOL=legacy, Claude and Gemini requests stay byte-identical to v0.1.62.

Recorded before K1 changed any code (main f28b52bc). Regenerate ONLY on purpose:
ARSLAN_UPDATE_GOLDEN=1 pytest tests/llm/test_k1_legacy_snapshot.py
"""
import json
import os
from pathlib import Path

import httpx
import pytest

from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from server.orchestrator import tool_loop
from server.registry import executors

GOLDEN = Path(__file__).parent / "golden" / "k1_legacy_payloads.json"

ANTHROPIC_REPLIES = [
    {"role": "assistant", "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5},
     "content": [{"type": "thinking", "thinking": "", "signature": "sig-one"},
                 {"type": "text", "text": "Searching."},
                 {"type": "tool_use", "id": "toolu_01", "name": "web_search", "input": {"query": "one"}},
                 {"type": "tool_use", "id": "toolu_02", "name": "web_search", "input": {"query": "two"}}]},
    {"role": "assistant", "stop_reason": "end_turn", "usage": {"input_tokens": 20, "output_tokens": 5},
     "content": [{"type": "text", "text": "Both done."}]},
]
GEMINI_REPLIES = [
    {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "web_search", "args": {"query": "one"}, "id": "fc1"}, "thoughtSignature": "ts"},
        {"functionCall": {"name": "web_search", "args": {"query": "two"}, "id": "fc2"}}]}}]},
    {"candidates": [{"content": {"parts": [{"text": "Both done."}]}}]},
]


class _Search:
    async def execute(self, args):
        return {"ok": True, "external": True, "summary": f"result-{args['query']}"}


async def _resolve():
    return [{"key": "web_search", "description": "Search the web"}]


async def _payloads(monkeypatch, provider_name, provider_cls, model, replies):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(sent) - 1])
    adapter = LLMAdapter(provider_name, model)
    adapter._provider = provider_cls(model, api_key="k", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Search())
    result = await tool_loop.run_native(system="S", user_content="Find two sources", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=_resolve)
    assert result["final"] == "Both done."
    return sent


@pytest.fixture
def legacy(monkeypatch):
    monkeypatch.setenv("ARSLAN_TOOL_PROTOCOL", "legacy")


async def test_legacy_requests_are_byte_identical_to_v0162(legacy, monkeypatch):
    got = {
        "anthropic": await _payloads(monkeypatch, "anthropic", AnthropicProvider, "claude-sonnet-5", ANTHROPIC_REPLIES),
        "gemini": await _payloads(monkeypatch, "gemini", GeminiProvider, "gemini-x", GEMINI_REPLIES),
    }
    if os.environ.get("ARSLAN_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    assert json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n" == GOLDEN.read_text()
