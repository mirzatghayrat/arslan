"""G1 — the tool transport layer: schemas must reach the provider, calls must come back.

The bug this file locks down: `chat(messages, tools=...)` is part of the
provider contract (base.py), OpenAI serialised `tools` into its payload, and
Anthropic and Gemini took the argument and threw it away. Since tool
descriptions are not in the system prompt either (tool_loop.py:1142 builds
`system + _NATIVE_EFFICIENCY + GUARD_NOTE` and nothing else), `tools=` was the
ONLY channel — so on those two providers the model never learned a single tool
existed, `tool_calls` came back empty every time, and run_native took its
"no tool_calls → this is the final answer" branch at step 0. Not a degraded
tool loop: no tool loop at all, and silent.

Ruling ①A: Anthropic this round, Gemini next. Gemini's tests here assert the
HONEST INTERIM STATE — it still drops, but it must now say so, because the
worse half of that bug was that nothing in the file admitted it.

Ruling ④B: `chat_stream` raises on `tools` rather than dropping them silently.
Silently dropping is the disease being cured; leaving a fresh outlet for it in
the same round would not survive review.
"""
from __future__ import annotations

import json

import httpx
import pytest

from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from arslan.llm.providers.openai_provider import OpenAIProvider

# The neutral shape `_native_tool_schemas` produces (tool_loop.py:938) and every
# provider must accept. Two tools, deliberately, so ORDER is observable.
NEUTRAL_TOOLS = [
    {"type": "function", "function": {
        "name": "web_search", "description": "Search the web.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "mcp_playwright_navigate", "description": "Open a URL.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
                       "required": ["url"]}}},
]


def _capture(captured: dict, response_json: dict):
    """Providers take a `transport=` at construction (the idiom already used in
    test_anthropic_provider.py) — there is no client-injection kwarg on chat()."""
    def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=response_json)
    return handler


_ANTHROPIC_TEXT = {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                   "usage": {"input_tokens": 1, "output_tokens": 1}}


# ---------------------------------------------------------------------------
# Request translation — the schemas must actually be on the wire
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anthropic_puts_the_tools_on_the_wire():
    captured: dict = {}
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                          transport=httpx.MockTransport(_capture(captured, _ANTHROPIC_TEXT)))
    await p.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                 tools=NEUTRAL_TOOLS)
    sent = captured["payload"].get("tools")
    assert sent, "Anthropic still drops `tools` — the whole point of G1"
    # Anthropic's field is `input_schema`, NOT OpenAI's nested function/parameters.
    assert [t["name"] for t in sent] == ["web_search", "mcp_playwright_navigate"]
    assert sent[0]["input_schema"] == NEUTRAL_TOOLS[0]["function"]["parameters"]
    assert "function" not in sent[0] and "parameters" not in sent[0]


@pytest.mark.asyncio
async def test_anthropic_sends_nothing_when_there_are_no_tools():
    """Discriminating: a translator that always emitted a `tools` key would pass
    the test above and send `"tools": []` on every toolless call — a payload
    change on the request path that has nothing to do with tools."""
    captured: dict = {}
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                          transport=httpx.MockTransport(_capture(captured, _ANTHROPIC_TEXT)))
    await p.chat([{"role": "user", "content": "u"}], tools=None)
    assert "tools" not in captured["payload"]


# ---------------------------------------------------------------------------
# Response parsing — a tool_use block must become a normalised tool_call
# ---------------------------------------------------------------------------

def test_anthropic_parses_a_tool_use_block_into_the_normalised_shape():
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k")
    data = {"role": "assistant", "stop_reason": "tool_use", "content": [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "toolu_01ABC", "name": "web_search",
         "input": {"query": "arslan"}},
    ], "usage": {"input_tokens": 1, "output_tokens": 1}}

    r = p._parse_response(data)

    assert len(r.tool_calls) == 1
    tc = r.tool_calls[0]
    # The shape run_native consumes, identical to OpenAI's (tool_loop reads
    # tc["function"]["name"] / ["arguments"] and does not branch on provider).
    assert tc["id"] == "toolu_01ABC"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "web_search"
    # arguments is a DICT here, matching openai_provider's post-parse shape —
    # Anthropic sends `input` already decoded, so re-encoding it to a string
    # would make run_native the only consumer that has to know which provider
    # answered.
    assert tc["function"]["arguments"] == {"query": "arslan"}
    # Narration survives alongside; run_native treats content as narration when
    # tool_calls is non-empty.
    assert r.content == "Let me look."


def test_anthropic_text_only_response_still_has_no_tool_calls():
    """Discriminating: a parser that appended a tool_call for every block would
    pass the test above and turn every plain answer into a phantom tool call —
    which run_native would dispatch."""
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k")
    r = p._parse_response(_ANTHROPIC_TEXT)
    assert r.tool_calls == []
    assert r.content == "ok"


def test_anthropic_parses_several_tool_use_blocks_in_one_reply():
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k")
    data = {"role": "assistant", "content": [
        {"type": "tool_use", "id": "a", "name": "web_search", "input": {"query": "x"}},
        {"type": "tool_use", "id": "b", "name": "web_extract", "input": {"url": "y"}},
    ], "usage": {}}
    r = p._parse_response(data)
    assert [t["function"]["name"] for t in r.tool_calls] == ["web_search", "web_extract"]
    assert [t["id"] for t in r.tool_calls] == ["a", "b"]


# ---------------------------------------------------------------------------
# §3 — serialisation must be byte-stable, or Anthropic's prompt cache dies
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_serialised_tools_are_byte_identical_across_calls():
    """Anthropic renders tools → system → messages with the cache breakpoint at
    the system prefix, so ANY reordering or key-order change in `tools`
    invalidates the whole prefix. This is the test that makes the ordering fix
    in resolve_tools load-bearing rather than cosmetic."""
    seen: list[str] = []

    def handler(request):
        seen.append(json.dumps(json.loads(request.content)["tools"], sort_keys=False))
        return httpx.Response(200, json=_ANTHROPIC_TEXT)

    p = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                          transport=httpx.MockTransport(handler))
    for _ in range(3):
        await p.chat([{"role": "user", "content": "u"}], tools=NEUTRAL_TOOLS)

    assert len(set(seen)) == 1, "tool serialisation is not byte-stable across calls"


# ---------------------------------------------------------------------------
# OpenAI — the baseline. It already worked; this pins it so the refactor
# cannot quietly change the one path the user's daily driver uses.
# ---------------------------------------------------------------------------

def test_openai_still_sends_the_neutral_schemas_untouched():
    """Asserted on `_payload` rather than over the wire because OpenAIProvider
    builds `httpx.AsyncClient()` inline with no injection point — unlike
    AnthropicProvider, which takes `transport=`. Testing the payload builder is
    what the existing OpenAI tests do, and it is the same function the real
    request serialises."""
    p = OpenAIProvider(model="gpt-4o", api_key="k")
    payload = p._payload([{"role": "user", "content": "u"}], NEUTRAL_TOOLS, 0.7)
    assert payload["tools"] == NEUTRAL_TOOLS, "the neutral shape must pass through untouched"


def test_openai_omits_the_key_when_there_are_no_tools():
    p = OpenAIProvider(model="gpt-4o", api_key="k")
    assert "tools" not in p._payload([{"role": "user", "content": "u"}], None, 0.7)


# ---------------------------------------------------------------------------
# Gemini — ①A puts it next round. What it owes NOW is the disclosure it never
# had: the word `tools` appeared exactly twice in that file, both in a
# signature, with no docstring or comment admitting the drop.
# ---------------------------------------------------------------------------

def test_gemini_admits_in_writing_that_it_drops_tools():
    import inspect

    # The MODULE, not just the class — mirroring where anthropic_provider puts
    # its own version of this disclosure (module docstring + an inline note at
    # the payload site), so the two providers are honest in the same place.
    src = inspect.getsource(inspect.getmodule(GeminiProvider))
    assert "tools" in src
    lowered = src.lower()
    assert ("not implemented" in lowered or "dropped" in lowered or "ignored" in lowered), (
        "Gemini still takes `tools` and discards it with nothing in the file saying so — "
        "the half of this bug that costs the NEXT reader, not the user"
    )


# ---------------------------------------------------------------------------
# ④B — chat_stream refuses rather than dropping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [
    AnthropicProvider(model="claude-opus-4-8", api_key="k"),
    OpenAIProvider(model="gpt-4o", api_key="k"),
    GeminiProvider(model="gemini-2.5-pro", api_key="k"),
])
async def test_chat_stream_refuses_tools_instead_of_dropping_them(provider):
    """run_native never streams (it only calls adapter.chat), so no caller passes
    tools here today. A signature that accepts them and silently discards them is
    exactly the shape of the bug this round exists to fix."""
    with pytest.raises(NotImplementedError):
        agen = provider.chat_stream([{"role": "user", "content": "u"}], tools=NEUTRAL_TOOLS)
        await agen.__anext__()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [
    AnthropicProvider(model="claude-opus-4-8", api_key="k"),
    OpenAIProvider(model="gpt-4o", api_key="k"),
    GeminiProvider(model="gemini-2.5-pro", api_key="k"),
])
async def test_chat_stream_without_tools_is_untouched(provider):
    """Discriminating: raising unconditionally would satisfy the test above and
    break every streaming caller in the app."""
    import inspect

    src = inspect.getsource(type(provider).chat_stream)
    assert "NotImplementedError" in src
    # The raise must be guarded by `tools`, not unconditional.
    raising_line = next(ln for ln in src.splitlines() if "NotImplementedError" in ln)
    guard_above = src[: src.index(raising_line)]
    assert "if tools" in guard_above, "chat_stream raises unconditionally"


# ---------------------------------------------------------------------------
# §3 / ruling ③A — the ordering that makes byte-stability achievable
# ---------------------------------------------------------------------------

def test_the_mcp_tool_query_is_ordered():
    """`_arslan_tools` reads MCP rows with a plain `select(Tool).where(...)`.
    Without an ORDER BY, row order is whatever SQLite hands back — harmless
    while nothing sends tools, and a per-request cache-buster the moment
    Anthropic starts receiving them (tools render before the system prefix that
    carries the cache breakpoint).

    Asserted on the query text rather than by executing it: an unordered SELECT
    is not RANDOM, it is merely UNSPECIFIED, so a live two-run comparison would
    pass today and still be unspecified tomorrow. That test would be the
    reassuring kind that cannot fail.
    """
    import inspect

    from server.orchestrator import arslan as arslan_mod

    src = inspect.getsource(arslan_mod._arslan_tools)
    assert 'Tool.toolset_key.like("mcp_%")' in src, "the MCP query moved — retarget this test"
    # Comments are stripped before the locality check: the first version of this
    # test measured a fixed character window and the explanatory comment ABOVE
    # the order_by pushed it out of range — a test that fails on prose length
    # tells you nothing about the query.
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    where_at = code.index('Tool.toolset_key.like("mcp_%")')
    assert "order_by" in code[where_at:where_at + 300], (
        "the MCP tool select has no ORDER BY; tool order is unspecified and every "
        "reorder costs a full Anthropic prompt-cache prefix"
    )


def test_the_anthropic_docstring_no_longer_cites_a_dead_protocol():
    """It claimed Arslan drove tools "via its own prompt/JSON protocol". That
    protocol is `tool_loop.run()`, which has zero production callers — only
    run_native is reachable (spawn_loop.py:49, arslan.py:1055). The disclosure
    outlived its reason, which is worse than no disclosure: it reads as a
    considered decision rather than a gap."""
    import inspect

    from arslan.llm.providers import anthropic_provider

    src = inspect.getsource(anthropic_provider)
    # The CLAIM, not the phrase. The present-tense sentence is what was false;
    # the file may — and does — still mention the old rationale in the past
    # tense to say why it was removed, which is the useful half.
    assert "drives tools via its own prompt/JSON protocol" not in src, (
        "the stale rationale is still asserted, and it now contradicts the code"
    )
    assert "native tool-use IS implemented" in src, (
        "nothing in the file states the current, true position"
    )


# ---------------------------------------------------------------------------
# Step 9 — the regression that actually matters: does run_native LOOP?
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_native_loops_on_anthropic_instead_of_answering_at_step_zero(monkeypatch):
    """The end-to-end shape of the bug, at the seam where it bit.

    Before G1 the Anthropic provider dropped the schemas, so `tool_calls` was
    empty on every reply and run_native took its "no tool_calls -> this is the
    final answer" branch at step 0. Asserting only "the answer mentions the
    tool" would NOT discriminate: a model that never called anything can still
    write the words. So this asserts the DISPATCH happened — the executor ran.
    """
    from server.orchestrator import tool_loop

    dispatched: list[str] = []

    class _Exec:
        """Dispatch goes through `resolve_executor(key)` -> object with
        `.execute(args)` (tool_loop.py:519,531). `EXECUTORS` itself is only
        consulted by the force_tools pre-run, so patching that dict — my first
        attempt — left the real dispatch path untouched and the tool never ran."""
        async def execute(self, args):
            dispatched.append(args.get("query", ""))
            return {"ok": True, "results": [{"title": "t", "snippet": "s"}], "external": True}

    async def fake_resolve_executor(key):
        return _Exec() if key == "web_search" else None

    monkeypatch.setattr(tool_loop, "resolve_executor", fake_resolve_executor)

    # Two Anthropic replies: a tool_use, then prose. The provider under test does
    # the parsing; only the HTTP boundary is faked.
    replies = [
        {"role": "assistant", "stop_reason": "tool_use", "content": [
            {"type": "tool_use", "id": "t1", "name": "web_search",
             "input": {"query": "arslan"}}],
         "usage": {"input_tokens": 1, "output_tokens": 1}},
        {"role": "assistant", "content": [{"type": "text", "text": "Final answer."}],
         "usage": {"input_tokens": 1, "output_tokens": 1}},
    ]
    seen_tools: list[bool] = []

    def handler(request):
        body = json.loads(request.content)
        seen_tools.append("tools" in body)
        return httpx.Response(200, json=replies[min(len(seen_tools) - 1, len(replies) - 1)])

    provider = AnthropicProvider(model="claude-opus-4-8", api_key="k",
                                 transport=httpx.MockTransport(handler))

    class _Adapter:
        async def chat(self, system, user, history=None, tools=None, **kw):
            msgs = [{"role": "system", "content": system}] + list(history or []) + [
                {"role": "user", "content": user}]
            return await provider.chat(msgs, tools=tools)

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _Adapter())

    out = await tool_loop.run_native(
        system="s", user_content="find something",
        resolve_tools=lambda: _fake_wired(), emit=lambda e: None,
        on_chunk=lambda c: None, history=[], tool_timeout_s=5,
        allow_escalation=False,
    )

    assert dispatched == ["arslan"], "the tool never actually ran — this is the bug"
    assert len(seen_tools) >= 2, "run_native did not take a second step"
    assert all(seen_tools), "a request went out with no tools on it"
    # Return shape is {"final", "escalation", "tool_trace"} — not "content".
    assert "Final answer." in (out.get("final") or ""), out
    assert [s["tool"] for s in out["tool_trace"]] == ["web_search"]


async def _fake_wired():
    return [{"key": "web_search", "description": "Search the web.",
             "input_schema": {"type": "object",
                              "properties": {"query": {"type": "string"}},
                              "required": ["query"]}}]


def test_translate_tools_never_returns_an_empty_list():
    """Makes an invariant explicit that was only accidental.

    Two mutations of the `if translated:` guard both stayed green, and the
    reason was not a gap in the tests: `_translate_tools` cannot return `[]`
    (`return out or None`), so `"tools": []` can never reach the wire whichever
    way that guard is written. That is worth a test rather than a coincidence —
    an empty array is a payload change on every toolless request, and on this
    provider a payload change is a prompt-cache change.
    """
    p = AnthropicProvider(model="claude-opus-4-8", api_key="k")
    assert p._translate_tools(None) is None
    assert p._translate_tools([]) is None
    # Non-empty input whose entries are all unusable must also collapse to None,
    # not to [].
    assert p._translate_tools([{"type": "function", "function": {}}]) is None
