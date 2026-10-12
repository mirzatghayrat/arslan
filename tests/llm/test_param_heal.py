"""A vendor that stops accepting an optional parameter heals itself (user 2026-10-13).

WHY: claude-sonnet-5-5 answered every request with 400 "`temperature` is
deprecated for this model." and nothing short of a new release could fix it —
the user had no switch, and the next vendor to retire a parameter would do the
same (OpenAI's gpt-5.6 models, the OpenAI preset's default, are listed by
OpenRouter as not taking `temperature` either, and Arslan sends 0.7). A table
of model rules can only be as new as the release it shipped in.

So: a 400/422 that NAMES an optional parameter this request actually sent is
answered by sending it again without that parameter (or, for OpenAI's
max_tokens, under the name the error asks for), and the endpoint+model is
remembered once the resend succeeded. Anything else fails exactly as before.

The error texts below are the vendors' own wording (Anthropic: the field
report; OpenAI: its unsupported_value / unsupported_parameter errors).
"""
import json

import httpx
import pytest

from arslan.llm import param_heal
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from arslan.llm.providers.openai_provider import OpenAIProvider

OPENAI = "https://api.openai.com/v1"
_PING = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "ping"}]

ANTHROPIC_TEMPERATURE = {"type": "error", "error": {
    "type": "invalid_request_error", "message": "`temperature` is deprecated for this model."}}
OPENAI_TEMPERATURE = {"error": {
    "message": "Unsupported value: 'temperature' does not support 0.7 with this model. "
               "Only the default (1) value is supported.",
    "type": "invalid_request_error", "param": "temperature", "code": "unsupported_value"}}
OPENAI_MAX_TOKENS = {"error": {
    "message": "Unsupported parameter: 'max_tokens' is not supported with this model. "
               "Use 'max_completion_tokens' instead.",
    "type": "invalid_request_error", "param": "max_tokens", "code": "unsupported_parameter"}}
GEMINI_TEMPERATURE = {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message":
    "Invalid value at 'generation_config.temperature': temperature is not supported for this model."}}


@pytest.fixture(autouse=True)
def _fresh():
    param_heal.forget()
    yield
    param_heal.forget()


class _Unread(httpx.AsyncByteStream):
    """An error body as the network delivers it: unread until someone reads it.
    A streamed request gets it this way; `response.text` raises until aread()."""

    def __init__(self, data: bytes):
        self.data = data

    async def __aiter__(self):
        yield self.data


class Vendor:
    """Refuses each listed parameter while it is present; records every body."""

    def __init__(self, refusals, ok_body, *, status=400, sse=None):
        self.refusals = refusals            # [(predicate(body), error_json)]
        self.ok_body, self.status, self.sse = ok_body, status, sse
        self.bodies = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.bodies.append(body)
        for present, error in self.refusals:
            if present(body):
                return httpx.Response(self.status, headers={"content-type": "application/json"},
                                      stream=_Unread(json.dumps(error).encode()))
        if self.sse is not None:
            return httpx.Response(200, text=self.sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=self.ok_body)


ANTHROPIC_OK = {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}
OPENAI_OK = {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}


def has(key):
    return lambda body: key in body


def _anthropic(vendor, model="kimi-k2", base="https://example.org/anthropic"):
    # A non-Claude model behind the Anthropic protocol still sends temperature
    # (the Claude rules of #174 do not apply to it) — the case the heal is for.
    return AnthropicProvider(model=model, api_key="k", base_url=base,
                             transport=httpx.MockTransport(vendor))


def _openai(vendor, model="gpt-5.6-terra", base=OPENAI):
    return OpenAIProvider(model=model, api_key="k", base_url=base, transport=httpx.MockTransport(vendor))


# ---- the heal itself ----------------------------------------------------------------

async def test_anthropic_protocol_drops_a_deprecated_temperature_and_remembers():
    v = Vendor([(has("temperature"), ANTHROPIC_TEMPERATURE)], ANTHROPIC_OK)
    p = _anthropic(v)
    assert (await p.chat(_PING)).content == "ok"
    assert ["temperature" in b for b in v.bodies] == [True, False]
    # Learned: a fresh provider for the same endpoint+model sends it no more.
    assert (await _anthropic(v).chat(_PING)).content == "ok"
    assert len(v.bodies) == 3 and "temperature" not in v.bodies[2]


async def test_openai_default_preset_model_heals_temperature_then_max_tokens():
    v = Vendor([(has("temperature"), OPENAI_TEMPERATURE), (has("max_tokens"), OPENAI_MAX_TOKENS)], OPENAI_OK)
    p = _openai(v)
    assert (await p.chat(_PING)).content == "ok"
    assert len(v.bodies) == 3
    last = v.bodies[-1]
    assert "temperature" not in last and "max_tokens" not in last
    assert last["max_completion_tokens"] == v.bodies[0]["max_tokens"]   # the budget survives the rename
    await _openai(v).chat(_PING)
    assert len(v.bodies) == 4 and "max_completion_tokens" in v.bodies[3] and "temperature" not in v.bodies[3]


async def test_gemini_nested_temperature_is_dropped():
    v = Vendor([(lambda b: "temperature" in b["generationConfig"], GEMINI_TEMPERATURE)], GEMINI_OK)
    p = GeminiProvider(model="gemini-9-pro", api_key="k", transport=httpx.MockTransport(v))
    assert (await p.chat(_PING)).content == "ok"
    assert "temperature" not in v.bodies[-1]["generationConfig"]
    assert v.bodies[-1]["generationConfig"]["maxOutputTokens"]           # the rest of the block stays


async def test_the_test_button_passes(monkeypatch):
    """What the user pressed: Settings → Test, through server/services/llm_test."""
    from server.services import llm_test
    v = Vendor([(has("temperature"), OPENAI_TEMPERATURE), (has("max_tokens"), OPENAI_MAX_TOKENS)], OPENAI_OK)
    monkeypatch.setattr(OpenAIProvider, "_client",
                        lambda self: httpx.AsyncClient(transport=httpx.MockTransport(v)))
    out = await llm_test.test_connection("openai", "gpt-5.6-terra", OPENAI, "sk-test")
    assert out["ok"] is True, out


# ---- streaming paths: healed before the first byte -----------------------------------

async def test_anthropic_stream_heals():
    sse = ('data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}\n\n'
           'data: {"type":"message_stop"}\n\n')
    v = Vendor([(has("temperature"), ANTHROPIC_TEMPERATURE)], None, sse=sse)
    out = [piece async for piece in _anthropic(v).chat_stream(_PING)]
    assert out == ["ok"] and "temperature" not in v.bodies[-1]


async def test_openai_text_stream_heals():
    sse = ('data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
           'data: [DONE]\n\n')
    v = Vendor([(has("temperature"), OPENAI_TEMPERATURE)], None, sse=sse)
    out = [piece async for piece in _openai(v).chat_stream(_PING)]
    assert out == ["ok"] and "temperature" not in v.bodies[-1]
    assert "stream_options" in v.bodies[-1]       # the heal is not the old "drop stream_options" fallback


async def test_openai_streamed_tool_turn_heals():
    sse = ('data: {"choices":[{"delta":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}\n\n'
           'data: [DONE]\n\n')
    v = Vendor([(has("temperature"), OPENAI_TEMPERATURE)], None, sse=sse)
    resp = await _openai(v).chat(_PING, stream=True)
    assert resp.content == "ok" and "temperature" not in v.bodies[-1]


async def test_gemini_stream_heals():
    sse = 'data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}\n\n'
    v = Vendor([(lambda b: "temperature" in b["generationConfig"], GEMINI_TEMPERATURE)], None, sse=sse)
    p = GeminiProvider(model="gemini-9-pro", api_key="k", transport=httpx.MockTransport(v))
    out = [piece async for piece in p.chat_stream(_PING)]
    assert out == ["ok"] and "temperature" not in v.bodies[-1]["generationConfig"]


# ---- what it must NOT do ----------------------------------------------------------------

@pytest.mark.parametrize("status,error", [
    (400, {"error": {"message": "This model's maximum context length is 128000 tokens."}}),
    (404, {"error": {"message": "The model `gpt-9` does not exist"}}),
    # Names temperature, but is not a refusal of it.
    (400, {"error": {"message": "temperature must be a number"}}),
    # A refusal, but the key/quota is the problem.
    (401, {"error": {"message": "temperature is not supported; invalid API key"}}),
    (429, {"error": {"message": "temperature unsupported; rate limited"}}),
])
async def test_other_errors_are_not_retried(status, error):
    v = Vendor([(lambda b: True, error)], OPENAI_OK, status=status)
    with pytest.raises(httpx.HTTPStatusError) as raised:
        await _openai(v).chat(_PING)
    assert len(v.bodies) == 1
    assert raised.value.response.status_code == status
    assert json.dumps(error["error"]["message"])[1:-1] in str(raised.value)   # the vendor's words still reach the user


async def test_a_parameter_that_was_not_sent_is_not_invented():
    """The error blames top_p; this request never sent top_p — nothing to drop."""
    err = {"error": {"message": "Unsupported parameter: 'top_p' is not supported with this model."}}
    v = Vendor([(lambda b: True, err)], OPENAI_OK)
    with pytest.raises(httpx.HTTPStatusError):
        await _openai(v).chat(_PING)
    assert len(v.bodies) == 1


async def test_nothing_is_learned_when_the_resend_fails_too():
    """An error that only mentions temperature in passing: the resend fails the
    same way, the original error surfaces, and the next request is unchanged."""
    err = {"error": {"message": "temperature is not supported in this region: content blocked"}}
    v = Vendor([(lambda b: True, err)], OPENAI_OK)
    with pytest.raises(httpx.HTTPStatusError):
        await _openai(v).chat(_PING)
    assert len(v.bodies) == 2
    with pytest.raises(httpx.HTTPStatusError):
        await _openai(v).chat(_PING)
    assert "temperature" in v.bodies[2]


async def test_learning_is_per_endpoint_and_model():
    v = Vendor([(lambda b: b["model"] == "gpt-5.6-terra" and "temperature" in b, OPENAI_TEMPERATURE)], OPENAI_OK)
    await _openai(v).chat(_PING)                                    # bodies 0 (refused), 1
    await _openai(v, model="gpt-4.1").chat(_PING)                   # body 2: another model
    await _openai(v, base="https://other.example/v1").chat(_PING)   # body 3: another endpoint, 4
    assert len(v.bodies) == 5
    assert "temperature" in v.bodies[2] and "temperature" in v.bodies[3]
    assert "temperature" not in v.bodies[4]


async def test_an_endpoint_that_keeps_refusing_stops():
    """Each parameter is healed once per request; a vendor that refuses
    everything cannot make the provider loop."""
    v = Vendor([(lambda b: True, OPENAI_TEMPERATURE)], OPENAI_OK)
    with pytest.raises(httpx.HTTPStatusError):
        await _openai(v).chat(_PING)
    assert len(v.bodies) == 2


async def test_the_error_param_field_alone_is_enough():
    err = {"error": {"message": "Unsupported value for this model.", "param": "temperature",
                     "code": "unsupported_value"}}
    v = Vendor([(has("temperature"), err)], OPENAI_OK)
    assert (await _openai(v).chat(_PING)).content == "ok"
    assert len(v.bodies) == 2 and "temperature" not in v.bodies[1]


async def test_max_tokens_is_renamed_only_to_the_name_the_error_asks_for():
    """No replacement named: the budget is not dropped and nothing is guessed."""
    err = {"error": {"message": "Unsupported parameter: 'max_tokens' is not supported with this model."}}
    v = Vendor([(has("max_tokens"), err)], OPENAI_OK)
    with pytest.raises(httpx.HTTPStatusError):
        await _openai(v, model="m", base="https://example.org/v1").chat(_PING, temperature=0.7)
    assert len(v.bodies) == 1


async def test_a_stream_that_already_produced_output_is_never_resent():
    """A resend after the first piece would show the user the start twice."""
    calls = []

    async def attempt(payload):
        calls.append(dict(payload))
        yield "Hel"
        req = httpx.Request("POST", "http://x")
        raise httpx.HTTPStatusError("400", request=req, response=httpx.Response(
            400, request=req, json=OPENAI_TEMPERATURE))

    out = []
    with pytest.raises(httpx.HTTPStatusError):
        async for piece in param_heal.stream("fp", {"temperature": 0.7}, attempt):
            out.append(piece)
    assert out == ["Hel"] and len(calls) == 1
