"""v0.1.64: the per-model output cap for OpenAI-compatible and Gemini keys leaves Claude and official
DeepSeek requests exactly as they were.

The golden file was recorded on main before that change (52ad7457). Regenerate ONLY on purpose:
ARSLAN_UPDATE_GOLDEN=1 pytest tests/llm/test_output_cap_unchanged_golden.py
"""
import json
import os
from pathlib import Path

import httpx

from arslan.llm import param_heal
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.openai_provider import OpenAIProvider

GOLDEN = Path(__file__).parent / "golden" / "output_cap_unchanged_payloads.json"

_MESSAGES = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "ping"}]
_TOOLS = [{"type": "function", "function": {"name": "web_search", "description": "Search the web",
                                            "parameters": {"type": "object",
                                                           "properties": {"query": {"type": "string"}}}}}]
_ANTHROPIC_REPLY = {"role": "assistant", "stop_reason": "end_turn", "usage": {"input_tokens": 3, "output_tokens": 1},
                    "content": [{"type": "text", "text": "ok"}]}
_OPENAI_REPLY = {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}
_SSE = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'


def _recorder(sent, reply):
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=reply)
    return handler


async def _anthropic(model):
    sent: list = []
    p = AnthropicProvider(model=model, api_key="k", transport=httpx.MockTransport(_recorder(sent, _ANTHROPIC_REPLY)))
    await p.chat(list(_MESSAGES))
    await p.chat(list(_MESSAGES), tools=_TOOLS)
    await p.chat(list(_MESSAGES), max_tokens=p.output_ceiling)
    await p.chat(list(_MESSAGES), tools=_TOOLS, stream=True)
    return {"max_tokens": p.max_tokens, "output_ceiling": p.output_ceiling, "payloads": sent}


async def _deepseek(model):
    sent: list = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if body.get("stream") and "tools" not in body:
            return httpx.Response(200, text=_SSE, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=_OPENAI_REPLY)
    p = OpenAIProvider(model=model, api_key="k", base_url="https://api.deepseek.com",
                       transport=httpx.MockTransport(handler))
    await p.chat(list(_MESSAGES))
    await p.chat(list(_MESSAGES), tools=_TOOLS, stream=True)
    await p.chat(list(_MESSAGES), max_tokens=p.output_ceiling)
    async for _ in p.chat_stream(list(_MESSAGES)):
        pass
    return {"max_tokens": p.max_tokens, "output_ceiling": p.output_ceiling, "payloads": sent}


async def test_claude_and_deepseek_payloads_are_byte_identical_to_main():
    param_heal.forget()
    got = {
        "anthropic/claude-sonnet-5-5": await _anthropic("claude-sonnet-5-5"),
        "anthropic/claude-opus-5-5": await _anthropic("claude-opus-5-5"),
        "deepseek/deepseek-v4-flash": await _deepseek("deepseek-v4-flash"),
        "deepseek/deepseek-v4-pro": await _deepseek("deepseek-v4-pro"),
    }
    text = json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("ARSLAN_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(text)
    assert text == GOLDEN.read_text()
