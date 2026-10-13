"""What each Claude generation accepts on the Messages API (field report 2026-10-13).

WHY: the user's own Anthropic key, model ``claude-sonnet-5-5``, answered every
request — the Test button included — with

    400 invalid_request_error "`temperature` is deprecated for this model."

The key was fine. The native provider sent ``temperature`` on every request, and
Claude Opus 4.7 and every later model refuse it (Sonnet 5 / 5.5 / Haiku 5.5 any
value but the default, Opus 4.7+ / Opus 5 / 5.5 / Fable any value at all);
omitting it is accepted by all of them. The same models think by default when
``thinking`` is omitted, so a critique that "never sends thinking" was not
thinking-free there either.

The fake API below answers the way the real one documents (claude-api skill,
model-migration guide; OpenRouter's public model list draws the same line:
temperature on Sonnet 4.6 / Haiku 4.5, none on Opus 4.8 and the 5.x models).
"""
import json

import httpx
import pytest

from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.request_policy import critique_request

# Models that refuse `temperature` (the default value excepted where noted).
REJECTS_SAMPLING = [
    "claude-sonnet-5-5", "claude-sonnet-5", "claude-haiku-5-5", "claude-opus-5-5",
    "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-fable-5-1",
    "claude-fable-5", "anthropic.claude-sonnet-5-5", "us.anthropic.claude-opus-4-8",
    # A Claude id we cannot place: omitting is accepted by every model, sending is not.
    "claude-sonnet-6", "claude-next",
]
ACCEPTS_SAMPLING = [
    "claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5", "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5", "claude-opus-4-1-20250805", "claude-sonnet-4-20250514",
    "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022", "claude-3-opus-20240229",
]


def _fake_api(sent: list):
    """Answer like api.anthropic.com for the rules this file is about."""
    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        model = body["model"]
        modern = model in REJECTS_SAMPLING
        if modern and "temperature" in body:
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error",
                "message": "`temperature` is deprecated for this model."}})
        thinking = (body.get("thinking") or {}).get("type")
        if thinking == "disabled" and model in {"claude-sonnet-5-5", "claude-opus-5-5",
                                                "claude-fable-5", "claude-fable-5-1"}:
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error",
                "message": '"thinking.type.disabled" is not supported for this model.'}})
        if thinking == "between_tools" and model != "claude-sonnet-5-5":
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error",
                "message": '"thinking.type.between_tools" is not supported for this model.'}})
        return httpx.Response(200, json={
            "role": "assistant", "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 3, "output_tokens": 1}})
    return handler


def _provider(model, sent):
    return AnthropicProvider(model=model, api_key="sk-ant-test",
                             transport=httpx.MockTransport(_fake_api(sent)))


_PING = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "ping"}]


@pytest.mark.parametrize("model", REJECTS_SAMPLING)
async def test_models_that_refuse_temperature_are_answered(model):
    """The field report itself: chat (what Test and every turn use) and stream."""
    sent: list = []
    p = _provider(model, sent)
    resp = await p.chat(_PING, temperature=0.7)
    assert resp.content == "ok"
    async for _ in p.chat_stream(_PING, temperature=0.7):
        pass
    # Every body, and exactly one per call: param_heal would also get these
    # answered, by resending — that must not be what makes this test pass.
    assert len(sent) == 2 and not any("temperature" in b for b in sent)


@pytest.mark.parametrize("model", ACCEPTS_SAMPLING)
async def test_older_models_keep_the_temperature_they_were_given(model):
    sent: list = []
    await _provider(model, sent).chat(_PING, temperature=0.3)
    assert sent[-1]["temperature"] == 0.3


async def test_a_compatible_endpoint_with_its_own_model_keeps_temperature():
    """A non-Claude model behind the Anthropic protocol is not governed by
    Anthropic's model rules; it keeps what it was sent before."""
    sent: list = []
    p = AnthropicProvider(model="kimi-k2", api_key="k", base_url="https://example.org/anthropic",
                          transport=httpx.MockTransport(_fake_api(sent)))
    await p.chat(_PING, temperature=0.3)
    assert sent[-1]["temperature"] == 0.3


async def test_a_normal_request_never_carries_a_thinking_setting():
    """Main turns keep each model's own default; only critiques change it."""
    for model in ["claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-4-6"]:
        sent: list = []
        await _provider(model, sent).chat(_PING)
        assert "thinking" not in sent[-1]


# ---- bounded critique: thinking provably off, or honestly unsupported ----------------

@pytest.mark.parametrize("model,switch", [
    ("claude-sonnet-5-5", {"type": "between_tools"}),   # disabled is a 400 here
    ("claude-sonnet-5", {"type": "disabled"}),
    ("claude-opus-5", {"type": "disabled"}),
    ("claude-haiku-5-5", {"type": "disabled"}),
])
async def test_critique_turns_thinking_off_where_the_model_can(model, switch):
    sent: list = []
    p = _provider(model, sent)
    assert p.supports_bounded_critique()
    with critique_request():
        assert (await p.chat(_PING)).content == "ok"
    body = sent[-1]
    assert body["thinking"] == switch
    assert body["max_tokens"] == 2048 and "temperature" not in body


@pytest.mark.parametrize("model", ["claude-opus-4-8", "claude-opus-4-7"])
async def test_critique_on_models_that_do_not_think_unless_asked(model):
    sent: list = []
    p = _provider(model, sent)
    assert p.supports_bounded_critique()
    with critique_request():
        await p.chat(_PING)
    assert "thinking" not in sent[-1] and "temperature" not in sent[-1]
    assert sent[-1]["max_tokens"] == 2048


async def test_critique_on_older_models_is_deterministic_and_short():
    sent: list = []
    p = _provider("claude-sonnet-4-6", sent)
    assert p.supports_bounded_critique()
    with critique_request():
        await p.chat(_PING)
    assert sent[-1]["temperature"] == 0 and sent[-1]["max_tokens"] == 2048
    assert "thinking" not in sent[-1]


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-fable-5-1", "claude-fable-5",
                                   "claude-sonnet-6", "kimi-k2"])
async def test_critique_where_thinking_cannot_be_turned_off_is_not_claimed(model):
    """Opus 5.5 / Fable refuse every off switch; an unknown model gives no proof.
    Claiming support would cap a thinking model at 2048 tokens — the 0.1.40
    failure (the cap spent on reasoning, nothing returned). So: not supported,
    and a critique there keeps the normal output budget."""
    sent: list = []
    p = _provider(model, sent)
    assert not p.supports_bounded_critique()
    with critique_request():
        await p.chat(_PING)
    assert "thinking" not in sent[-1]
    assert sent[-1]["max_tokens"] == p.max_tokens > 2048


async def test_critique_with_tools_is_a_normal_request():
    sent: list = []
    tools = [{"type": "function", "function": {"name": "t", "parameters": {"type": "object"}}}]
    with critique_request():
        await _provider("claude-sonnet-5-5", sent).chat(_PING, tools=tools)
    assert "thinking" not in sent[-1] and sent[-1]["max_tokens"] != 2048


# ---- output budget: thinking and the answer share max_tokens --------------------------

async def test_output_budget_matches_the_other_providers_and_can_be_raised():
    """Claude 5+ thinks by default and the thinking is billed against max_tokens,
    so the old flat 4096 could be spent before the answer or a tool call was
    written. Same opening budget and length-cut ceiling as the OpenAI-compatible
    path (output_budget.py); tool_loop._recover_truncation raises a cut request
    through chat(max_tokens=...)."""
    sent: list = []
    p = _provider("claude-sonnet-5-5", sent)
    assert p.max_tokens == 8192 and p.output_ceiling == 16384
    await p.chat(_PING)
    assert sent[-1]["max_tokens"] == 8192
    await p.chat(_PING, max_tokens=p.output_ceiling)
    assert sent[-1]["max_tokens"] == 16384


async def test_non_streamed_reply_gets_the_same_first_byte_timeout_as_openai():
    """model_call.py documents a non-streamed reply as bounded by httpx's 300 s;
    this provider used 60 s, which a thinking model can need before its first byte."""
    seen = {}

    def handler(request):
        seen.update(request.extensions["timeout"])
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    p = AnthropicProvider(model="claude-sonnet-5-5", api_key="k",
                          transport=httpx.MockTransport(handler))
    await p.chat(_PING)
    assert seen["read"] == 300.0 and seen["connect"] == 15.0


async def test_a_cut_reply_is_raised_then_continued_through_the_real_loop(monkeypatch):
    """End to end through run_native (the legacy rendering Anthropic gets): a
    reply cut at max_tokens is re-sent at the ceiling, then continued — before,
    this provider had no ceiling, so a cut reply stayed cut."""
    from arslan.execution_budget import Budget, Limits, scope
    from arslan.llm.adapter import LLMAdapter
    from server.orchestrator import model_call, tool_loop

    replies = [("Hel", "max_tokens"), ("Hello wor", "max_tokens"), ("ld.", "end_turn")]
    sent: list = []

    def handler(request):
        sent.append(json.loads(request.content))
        text, stop = replies.pop(0)
        return httpx.Response(200, json={
            "role": "assistant", "content": [{"type": "text", "text": text}],
            "stop_reason": stop, "usage": {"input_tokens": 10, "output_tokens": 5}})

    async def no_sleep(_):
        return None
    monkeypatch.setattr(model_call, "sleep", no_sleep)
    adapter = LLMAdapter("anthropic", "claude-sonnet-5-5", api_key="k")
    adapter._provider = AnthropicProvider(model="claude-sonnet-5-5", api_key="k",
                                          transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def tools():
        return [{"key": "web_search", "description": "search"}]
    with scope(Budget(Limits(tokens=10_000_000))):
        out = await tool_loop.run_native(system="S", user_content="task", history=[],
                                         emit=lambda e: None, on_chunk=lambda c: None,
                                         resolve_tools=tools)
    assert out["final"] == "Hello world."
    assert [b["max_tokens"] for b in sent] == [8192, 16384, 16384]
    assert not any("temperature" in b for b in sent)
