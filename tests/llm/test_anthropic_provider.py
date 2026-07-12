"""Tests for the native AnthropicProvider (Tier 1)."""
import json

import httpx

from arslan.llm.adapter import LLMAdapter
from arslan.llm.cached_system import build_cached_system
from arslan.llm.providers.anthropic_provider import AnthropicProvider


def _capture_handler(captured: dict):
    def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                  "usage": {"input_tokens": 1, "output_tokens": 1}},
        )
    return handler


def test_provider_name_and_default_base_url():
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k")
    assert p.provider_name == "anthropic"
    assert p.base_url == AnthropicProvider.DEFAULT_BASE_URL


def test_split_system_separates_system_from_conversation():
    p = AnthropicProvider(model="claude-opus-4-8")
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "more"},
    ]
    system, convo = p._split_system(messages)
    assert system == "You are helpful."
    assert convo == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "more"},
    ]


def test_parse_response_joins_text_blocks():
    p = AnthropicProvider(model="claude-opus-4-8")
    data = {
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello "}, {"type": "text", "text": "world"}],
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    resp = p._parse_response(data)
    assert resp.content == "Hello world"
    assert resp.usage["output_tokens"] == 2


async def test_chat_sends_anthropic_format():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                  "usage": {"input_tokens": 1, "output_tokens": 1}},
        )

    p = AnthropicProvider(model="claude-opus-4-8", api_key="sk-ant",
                          transport=httpx.MockTransport(handler))
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "hi"},
    ]
    resp = await p.chat(messages, temperature=0.5)

    assert resp.content == "ok"
    assert captured["url"].endswith("/messages")
    assert captured["headers"]["x-api-key"] == "sk-ant"
    assert captured["headers"]["anthropic-version"]
    # system is a TOP-LEVEL field, not a message
    assert captured["payload"]["system"] == "SYS"
    assert {"role": "system"} not in [{"role": m["role"]} for m in captured["payload"]["messages"]]
    assert "max_tokens" in captured["payload"]


async def test_chat_stream_yields_text_deltas():
    sse = (
        'data: {"type":"message_start"}\n\n'
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"He"}}\n\n'
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"llo"}}\n\n'
        'data: {"type":"message_stop"}\n\n'
    )

    def handler(request):
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    p = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                          transport=httpx.MockTransport(handler))
    out = []
    async for piece in p.chat_stream([{"role": "user", "content": "hi"}]):
        out.append(piece)
    assert "".join(out) == "Hello"


def test_adapter_registers_anthropic_provider():
    adapter = LLMAdapter("anthropic", "claude-opus-4-8", api_key="k")
    assert isinstance(adapter._provider, AnthropicProvider)


# ---- prompt-cache reorder (D4): cache_control content-block array --------------------

async def test_cached_system_becomes_block_array_with_cache_control():
    """A CachedSystem system → system is a content-block array: the stable prefix is a
    cached block (cache_control ephemeral), the volatile suffix a separate un-cached block.
    The concatenation of the block texts is byte-identical to the full system string."""
    captured = {}
    p = AnthropicProvider(model="claude-opus-4-8", api_key="sk-ant",
                          transport=httpx.MockTransport(_capture_handler(captured)))
    system = build_cached_system("STABLE GUARDS", "\n\nvolatile roster/facts/date")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "hi"},
    ]
    await p.chat(messages)

    blocks = captured["payload"]["system"]
    assert isinstance(blocks, list)
    assert blocks[0] == {"type": "text", "text": "STABLE GUARDS",
                         "cache_control": {"type": "ephemeral"}}
    # Last static (cached) block is the stable prefix; the volatile tail is uncached.
    assert blocks[1] == {"type": "text", "text": "\n\nvolatile roster/facts/date"}
    assert "cache_control" not in blocks[1]
    # Behavior preservation: the model sees exactly the same bytes as the string form.
    assert "".join(b["text"] for b in blocks) == str(system)


async def test_ttl_is_default_5min_ephemeral_no_1h():
    captured = {}
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                          transport=httpx.MockTransport(_capture_handler(captured)))
    system = build_cached_system("STABLE", "\n\nvol")
    await p.chat([{"role": "system", "content": system}, {"role": "user", "content": "hi"}])
    cc = captured["payload"]["system"][0]["cache_control"]
    assert cc == {"type": "ephemeral"}  # default 5-minute TTL; no {"ttl": "1h"}


async def test_plain_string_system_stays_a_string_no_cache_control():
    """A plain-str system (spawns, tests, non-reordered callers) is unchanged: a bare
    string, no cache_control block — zero behavior change for those paths."""
    captured = {}
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                          transport=httpx.MockTransport(_capture_handler(captured)))
    await p.chat([{"role": "system", "content": "PLAIN"}, {"role": "user", "content": "hi"}])
    assert captured["payload"]["system"] == "PLAIN"


async def test_empty_volatile_yields_single_cached_block():
    """Router case: volatile == "" (dynamic content is in the user message) → one cached
    block, no trailing volatile block, value byte-identical to the stable rubric."""
    captured = {}
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                          transport=httpx.MockTransport(_capture_handler(captured)))
    system = build_cached_system("RUBRIC", "")
    await p.chat([{"role": "system", "content": system}, {"role": "user", "content": "x"}])
    blocks = captured["payload"]["system"]
    assert blocks == [{"type": "text", "text": "RUBRIC", "cache_control": {"type": "ephemeral"}}]


async def test_under_floor_prefix_still_constructs_no_error():
    """R4 floor degrade: a stable prefix below a model's minimum-cacheable floor is simply
    not honored by Anthropic — it does NOT error. The request must still construct fine;
    we do not gate/branch on model floor."""
    captured = {}
    p = AnthropicProvider(model="claude-haiku-4-5", api_key="k",
                          transport=httpx.MockTransport(_capture_handler(captured)))
    system = build_cached_system("tiny", "\n\nvol")  # well under any floor
    resp = await p.chat([{"role": "system", "content": system}, {"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert captured["payload"]["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_tools_present_still_constructs_and_not_serialized():
    """Arslan's Anthropic path is intentionally text-in/text-out (native tool-use is not
    implemented — the OpenAI-protocol convo is incompatible with Anthropic's strict
    tool_use/tool_result block pairing). So tools passed to chat() are NOT serialized into
    the Anthropic payload (unchanged behavior); D3's 'cache_control on the last tool' is
    N/A because there is no tool block. The request must still construct with tools passed."""
    captured = {}
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                          transport=httpx.MockTransport(_capture_handler(captured)))
    system = build_cached_system("STABLE", "\n\nvol")
    tools = [{"type": "function", "function": {"name": "web_search", "parameters": {}}}]
    resp = await p.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": "hi"}], tools=tools)
    assert resp.content == "ok"
    assert "tools" not in captured["payload"]
    assert captured["payload"]["system"][0]["cache_control"] == {"type": "ephemeral"}
