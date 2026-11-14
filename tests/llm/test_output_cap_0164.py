"""v0.1.64: OpenAI-compatible and Gemini keys declare each model's documented maximum output.

The old flat 8,192 cut long work short. A listed model gets its vendor's documented maximum
(output_budget.DOCUMENTED_MAX_OUTPUT), an unknown or custom model 32,768, under the parameter name its
family takes. An endpoint that refuses the declared cap is asked once more at 8,192, and a reply that
still stops on the length limit is continued (model_step._recover_truncation).
"""
import json

import httpx
import pytest

from arslan.llm import output_budget, param_heal
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.gemini_provider import GeminiProvider
from arslan.llm.providers.openai_provider import OpenAIProvider
from server.orchestrator import model_step, tool_loop

_MESSAGES = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "ping"}]
_OPENAI_OK = {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}
_GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
_SSE = ('data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')


@pytest.fixture(autouse=True)
def _fresh_heals():
    param_heal.forget()
    yield
    param_heal.forget()


def _openai(model, base_url="", replies=None):
    sent: list = []
    replies = list(replies or [])

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if replies:
            return replies.pop(0)
        if body.get("stream"):
            return httpx.Response(200, text=_SSE, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=_OPENAI_OK)
    return OpenAIProvider(model=model, api_key="k", base_url=base_url, transport=httpx.MockTransport(handler)), sent


def _gemini(model, replies=None):
    sent: list = []
    replies = list(replies or [])

    def handler(request):
        sent.append(json.loads(request.content))
        return replies.pop(0) if replies else httpx.Response(200, json=_GEMINI_OK)
    return GeminiProvider(model=model, api_key="k", transport=httpx.MockTransport(handler)), sent


def _cap(body):
    keys = [k for k in ("max_tokens", "max_completion_tokens") if k in body]
    assert len(keys) == 1, body
    return keys[0], body[keys[0]]


# ---- the request carries each model's documented cap ----------------------------------------------------

@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"])
async def test_listed_openai_models_declare_their_documented_cap(model):
    p, sent = _openai(model)
    await p.chat(list(_MESSAGES))
    assert _cap(sent[-1]) == ("max_completion_tokens", 128_000)


@pytest.mark.parametrize("model", ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-2.5-pro", "gemini-2.5-flash"])
async def test_listed_gemini_models_declare_their_documented_cap(model):
    p, sent = _gemini(model)
    await p.chat(list(_MESSAGES))
    async for _ in p.chat_stream(list(_MESSAGES)):
        pass
    assert [b["generationConfig"]["maxOutputTokens"] for b in sent] == [65_536, 65_536]


def test_every_seeded_openai_and_gemini_model_has_a_documented_cap():
    """A model the catalog lists by default never falls back to the unknown default."""
    from arslan.llm.catalog import models_for
    listed = models_for("openai") + models_for("gemini")
    assert listed and all(m in output_budget.DOCUMENTED_MAX_OUTPUT for m in listed), listed


# ---- unknown models get 32,768 ------------------------------------------------------------------------

@pytest.mark.parametrize("model,base", [
    ("my-finetune", "http://127.0.0.1:8000/v1"),
    ("qwen3.7-max", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    ("openai/gpt-5.6-terra", "https://openrouter.ai/api/v1"),
    ("deepseek-v4-flash", "https://example-proxy.invalid/v1"),          # DeepSeek's id, not DeepSeek's host
])
async def test_unknown_openai_compatible_models_get_32768(model, base):
    p, sent = _openai(model, base)
    await p.chat(list(_MESSAGES))
    assert _cap(sent[-1]) == ("max_tokens", 32_768)
    assert p.max_tokens == p.output_ceiling == 32_768


@pytest.mark.parametrize("model", ["deepseek-chat", "deepseek-reasoner", "fixture-model"])
@pytest.mark.parametrize("base", sorted(output_budget.DEEPSEEK_BASES))
async def test_official_deepseek_host_keeps_mains_budget_for_any_model(model, base):
    """Official DeepSeek is unchanged for every id, listed or not: an unlisted id keeps main's 8,192
    opening budget and 16,384 ceiling (the stable-eval spend guard reserves against exactly 8,192)."""
    p, sent = _openai(model, base)
    await p.chat(list(_MESSAGES))
    assert _cap(sent[-1]) == ("max_tokens", 8_192)
    assert (p.max_tokens, p.output_ceiling) == (8_192, 16_384)


async def test_unknown_gemini_model_gets_32768():
    p, sent = _gemini("gemini-future-pro")
    await p.chat(list(_MESSAGES))
    assert sent[-1]["generationConfig"]["maxOutputTokens"] == 32_768


def test_an_explicit_budget_still_wins():
    assert OpenAIProvider(model="gpt-5.6-terra", max_tokens=1000).max_tokens == 1000


# ---- the parameter name per family -------------------------------------------------------------------

@pytest.mark.parametrize("model,base,expected", [
    ("gpt-5.6-terra", "", "max_completion_tokens"),
    ("o4-mini", "", "max_completion_tokens"),
    ("gpt-5.6-terra", "https://my-gateway.invalid/v1", "max_completion_tokens"),
    ("openai/gpt-5.6-terra", "https://openrouter.ai/api/v1", "max_tokens"),
    ("llama-3.3-70b-versatile", "https://api.groq.com/openai/v1", "max_tokens"),
    ("gpt-oss-20b", "http://127.0.0.1:11434/v1", "max_tokens"),
])
async def test_parameter_name_follows_the_model_family(model, base, expected):
    p, sent = _openai(model, base)
    await p.chat(list(_MESSAGES))
    await p.chat(list(_MESSAGES), stream=True)
    async for _ in p.chat_stream(list(_MESSAGES)):
        pass
    assert [_cap(b)[0] for b in sent] == [expected] * 3


# ---- a refused cap is asked once more at 8,192 ---------------------------------------------------------

def _refusal(status, message, param=None):
    return httpx.Response(status, json={"error": {"message": message, "type": "invalid_request_error",
                                                  "param": param, "code": "invalid_value"}})


async def test_openai_refused_cap_is_resent_once_at_8192():
    refusal = _refusal(400, "max_completion_tokens is too large: 128000. This model supports at most "
                            "100000 completion tokens, whereas you provided 128000.", "max_completion_tokens")
    p, sent = _openai("gpt-5.6-terra", replies=[refusal])
    resp = await p.chat(list(_MESSAGES))
    assert resp.content == "ok"
    assert [_cap(b) for b in sent] == [("max_completion_tokens", 128_000), ("max_completion_tokens", 8_192)]


async def test_openrouter_credit_refusal_is_resent_once_at_8192():
    refusal = _refusal(402, "This request requires more credits, or fewer max_tokens. You requested up to "
                            "32768 tokens, but can only afford 20000.")
    p, sent = _openai("some/model", "https://openrouter.ai/api/v1", replies=[refusal])
    await p.chat(list(_MESSAGES), tools=None, stream=True)
    assert [_cap(b)[1] for b in sent] == [32_768, 8_192]


async def test_text_stream_refused_cap_is_resent_once_at_8192():
    refusal = _refusal(400, "`max_tokens` must be less than or equal to `8192`, the maximum value for "
                            "`max_tokens` is less than the `context_window` for this model")
    p, sent = _openai("llama-3.1-8b-instant", "https://api.groq.com/openai/v1", replies=[refusal])
    assert [piece async for piece in p.chat_stream(list(_MESSAGES))] == ["ok"]
    assert [_cap(b)[1] for b in sent] == [32_768, 8_192]


async def test_gemini_refused_cap_is_resent_once_at_8192():
    refusal = httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message":
                             "The maxOutputTokens value 65536 is out of range for this model."}})
    p, sent = _gemini("gemini-2.5-flash", replies=[refusal])
    resp = await p.chat(list(_MESSAGES))
    assert resp.content == "ok"
    assert [b["generationConfig"]["maxOutputTokens"] for b in sent] == [65_536, 8_192]


async def test_the_fallback_is_tried_once_and_only_for_a_refused_cap():
    cap_refusal = _refusal(400, "max_tokens is too large", "max_tokens")
    p, sent = _openai("custom", "http://127.0.0.1:8000/v1", replies=[cap_refusal, cap_refusal])
    with pytest.raises(httpx.HTTPStatusError):
        await p.chat(list(_MESSAGES))
    assert [_cap(b)[1] for b in sent] == [32_768, 8_192]          # once, not a loop

    other = _refusal(400, "Invalid value for messages[0].content", "messages")
    p, sent = _openai("custom", "http://127.0.0.1:8000/v1", replies=[other])
    with pytest.raises(httpx.HTTPStatusError):
        await p.chat(list(_MESSAGES))
    assert len(sent) == 1                                          # not about the cap: no resend

    auth = httpx.Response(401, json={"error": {"message": "Incorrect API key; max_tokens irrelevant"}})
    p, sent = _openai("custom", "http://127.0.0.1:8000/v1", replies=[auth])
    with pytest.raises(httpx.HTTPStatusError):
        await p.chat(list(_MESSAGES))
    assert len(sent) == 1


async def test_a_refused_cap_is_remembered_per_endpoint_and_model():
    """After one refusal, later requests to that endpoint and model open at 8,192: no refused round trip each time."""
    refusal = _refusal(400, "max_tokens is too large", "max_tokens")
    base = "http://127.0.0.1:8000/v1"
    p, sent = _openai("custom", base, replies=[refusal])
    await p.chat(list(_MESSAGES))
    assert [_cap(b)[1] for b in sent] == [32_768, 8_192]
    await p.chat(list(_MESSAGES))
    assert [_cap(b)[1] for b in sent[2:]] == [8_192]                 # straight to 8,192, one request
    assert [piece async for piece in p.chat_stream(list(_MESSAGES))] == ["ok"]
    assert [_cap(b)[1] for b in sent[3:]] == [8_192]                 # the stream path too

    again, sent = _openai("custom", base)                            # a new provider for the same endpoint + model
    await again.chat(list(_MESSAGES))
    assert [_cap(b)[1] for b in sent] == [8_192]

    other_model, sent = _openai("custom-large", base)
    await other_model.chat(list(_MESSAGES))
    other_base, sent2 = _openai("custom", "http://127.0.0.1:9000/v1")
    await other_base.chat(list(_MESSAGES))
    assert [_cap(b)[1] for b in sent] == [32_768] and [_cap(b)[1] for b in sent2] == [32_768]


async def test_gemini_refused_cap_is_remembered():
    refusal = httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT", "message":
                             "The maxOutputTokens value 65536 is out of range for this model."}})
    p, sent = _gemini("gemini-2.5-flash", replies=[refusal])
    await p.chat(list(_MESSAGES))
    await p.chat(list(_MESSAGES))
    assert [b["generationConfig"]["maxOutputTokens"] for b in sent] == [65_536, 8_192, 8_192]


async def test_an_explicit_smaller_cap_is_kept_on_a_remembered_endpoint():
    refusal = _refusal(400, "max_tokens is too large", "max_tokens")
    p, sent = _openai("custom", "http://127.0.0.1:8000/v1", replies=[refusal])
    await p.chat(list(_MESSAGES))
    await p.chat(list(_MESSAGES), max_tokens=1_024)
    assert [_cap(b)[1] for b in sent] == [32_768, 8_192, 1_024]


# ---- a length stop is continued, not silently cut ------------------------------------------------------

async def _run(monkeypatch, adapter):
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def _no_tools():
        return []
    return await tool_loop.run_native(system="S", user_content="Write the long report", history=[],
                                      emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=_no_tools)


async def test_openai_length_stop_is_continued(monkeypatch):
    cut = httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "First half,"},
                                                 "finish_reason": "length"}]})
    rest = httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": " second half."},
                                                  "finish_reason": "stop"}]})
    provider, sent = _openai("gpt-5.6-terra", replies=[cut, rest])
    adapter = LLMAdapter("openai", "gpt-5.6-terra", api_key="k")
    adapter._provider = provider
    result = await _run(monkeypatch, adapter)
    assert result["final"] == "First half, second half."
    assert len(sent) == 2 and model_step.CONTINUE_PROMPT in json.dumps(sent[1]["messages"])


async def test_gemini_length_stop_is_continued(monkeypatch):
    cut = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "First half,"}]},
                                                    "finishReason": "MAX_TOKENS"}]})
    rest = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": " second half."}]},
                                                     "finishReason": "STOP"}]})
    provider, sent = _gemini("gemini-3.5-flash", replies=[cut, rest])
    adapter = LLMAdapter("gemini", "gemini-3.5-flash", api_key="k")
    adapter._provider = provider
    result = await _run(monkeypatch, adapter)
    assert result["final"] == "First half, second half."
    assert len(sent) == 2 and model_step.CONTINUE_PROMPT in json.dumps(sent[1]["contents"])
