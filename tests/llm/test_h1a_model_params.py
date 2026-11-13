"""H1-a (v0.1.64): Claude's effort and Claude's raised output cap, each behind its own settings switch (harness plan §4.3: measured off against on through BENCH_ARSLAN_SETTINGS).

The golden holds the request bodies each adapter sent on main 1dedec970, before H1-a changed any code, byte for byte.
Regenerate ONLY on purpose: ARSLAN_UPDATE_GOLDEN=1 pytest tests/llm/test_h1a_model_params.py
"""
import json
import os
from pathlib import Path

import httpx
import pytest

from arslan.llm.adapter import LLMAdapter

GOLDEN = Path(__file__).parent / "golden" / "h1a_payloads_main.json"

#: name -> (protocol, model, base_url). Non-official hosts for Claude and Gemini so `chat` answers whole (no SSE).
CASES = {
    "deepseek": ("openai", "deepseek-v4-pro", "https://api.deepseek.com"),
    "openai": ("openai", "gpt-5.6-terra", ""),
    "openai_old": ("openai", "gpt-4o", ""),
    "compatible": ("openai", "qwen3-coder", "http://127.0.0.1:11434/v1"),
    "openrouter": ("openai", "anthropic/claude-sonnet-5", "https://openrouter.ai/api/v1"),
    "gemini": ("gemini", "gemini-3.6-flash", "https://gemini-proxy.example/v1beta"),
    "gemini_old": ("gemini", "gemini-2.0-flash", "https://gemini-proxy.example/v1beta"),
    "claude": ("anthropic", "claude-opus-5-5", "https://claude-proxy.example/v1"),
    "claude46": ("anthropic", "claude-sonnet-4-6", "https://claude-proxy.example/v1"),
    "claude45": ("anthropic", "claude-sonnet-4-5", "https://claude-proxy.example/v1"),
    "claude3": ("anthropic", "claude-3-5-haiku-20241022", "https://claude-proxy.example/v1"),
}
TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "Read a file",
                                           "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                                                          "required": ["path"]}}}]
REPLIES = {
    "openai": {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}},
    "gemini": {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}],
               "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1, "totalTokenCount": 4}},
    "anthropic": {"role": "assistant", "stop_reason": "end_turn", "usage": {"input_tokens": 3, "output_tokens": 1},
                  "content": [{"type": "text", "text": "ok"}]},
}


async def _bodies(name, **adapter_kwargs) -> list[str]:
    """The raw bodies one adapter sends: a request with tools (tool work), then one without."""
    protocol, model, base_url = CASES[name]
    sent = []

    def handler(request):
        sent.append(request.content.decode())
        return httpx.Response(200, json=REPLIES[protocol])
    adapter = LLMAdapter(protocol, model, api_key="k", base_url=base_url, **adapter_kwargs)
    adapter._provider._transport = httpx.MockTransport(handler)
    await adapter.chat("S", "Read notes.md", tools=TOOLS)
    await adapter.chat("S", "Say hi")
    return sent


async def _all(**adapter_kwargs) -> dict[str, list[str]]:
    return {name: await _bodies(name, **adapter_kwargs) for name in CASES}


async def test_requests_are_byte_identical_to_main_without_switches():
    got = await _all()
    if os.environ.get("ARSLAN_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    assert got == json.loads(GOLDEN.read_text())


# ---- with the switches -------------------------------------------------------------------------------------------

def _switches(**on):
    from arslan.llm.model_params import Switches
    return Switches(**on)


def _golden():
    return json.loads(GOLDEN.read_text())


async def test_every_switch_at_its_old_value_is_byte_identical_to_main():
    assert await _all(switches=_switches()) == _golden()


@pytest.mark.parametrize("level", ["high", "medium"])
async def test_claude_effort_is_sent_to_the_claude_models_that_take_it(level):
    got, gold = await _all(switches=_switches(claude_effort=level)), _golden()
    for name in ("claude", "claude46"):
        for sent, before in zip(got[name], gold[name]):
            body = json.loads(sent)
            assert body.pop("output_config") == {"effort": level}, name
            assert body == json.loads(before), name
    for name in CASES:
        if name not in ("claude", "claude46"):                            # Sonnet 4.5, Claude 3, other vendors
            assert got[name] == gold[name], name


async def test_the_raised_output_cap_goes_to_claude_4_5_and_later_only():
    got, gold = await _all(switches=_switches(output_cap=True)), _golden()
    for name in ("claude", "claude46", "claude45"):
        for sent, before in zip(got[name], gold[name]):
            body = json.loads(sent)
            assert body.pop("max_tokens") == 32_768, name
            assert body == {k: v for k, v in json.loads(before).items() if k != "max_tokens"}, name
    # Claude 3 cannot take it; the OpenAI-compatible and Gemini caps were removed unmeasured (no keys).
    for name in CASES:
        if name not in ("claude", "claude46", "claude45"):
            assert got[name] == gold[name], name


def test_the_raised_cap_raises_the_length_cut_ceiling_with_it():
    from arslan.llm.model_params import configure
    provider = LLMAdapter("anthropic", "claude-opus-5-5", api_key="k", base_url=CASES["claude"][2])._provider
    configure(provider, _switches(output_cap=True))
    assert (provider.max_tokens, provider.output_ceiling) == (32_768, 65_536)
