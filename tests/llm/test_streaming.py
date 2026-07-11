"""LLM streaming tests for the OpenAI-compatible provider and adapter."""
import copy

import httpx
import pytest

from arslan.llm import usage_sink
from arslan.llm.providers.base import BaseLLMProvider


class _StubProvider(BaseLLMProvider):
    """Provider with no real chat_stream override, to test the default."""

    @property
    def provider_name(self) -> str:
        return "stub"

    async def chat(self, messages, tools=None, temperature=0.7):
        from arslan.models import LLMResponse

        return LLMResponse(content="hello world", usage={})


@pytest.mark.asyncio
async def test_default_chat_stream_yields_full_content():
    provider = _StubProvider(model="x")
    chunks = []
    async for piece in provider.chat_stream([{"role": "user", "content": "hi"}]):
        chunks.append(piece)
    assert "".join(chunks) == "hello world"


@pytest.mark.asyncio
async def test_openai_chat_stream_parses_sse(monkeypatch):
    """OpenAIProvider.chat_stream should yield deltas parsed from SSE lines."""
    import arslan.llm.providers.openai_provider as op

    sse_lines = [
        "",  # blank keep-alive line
        ": ping",  # SSE comment line
        'data: {"choices":[{"delta":{"role":"assistant"}}]}',  # role-only, no content
        'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        "data: not-json",  # malformed -> skipped
        'data: {"choices":[]}',  # empty choices -> skipped
        '  data: {"choices":[{"delta":{"content":" there"}}]}',  # leading whitespace
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"AFTER-DONE"}}]}',  # must NOT appear (after [DONE])
    ]

    class _FakeStreamResponse:
        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            for line in sse_lines:
                yield line

    class _FakeStreamCtx:
        async def __aenter__(self):
            return _FakeStreamResponse()

        async def __aexit__(self, *exc):
            return False

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, **kwargs):
            return _FakeStreamCtx()

    monkeypatch.setattr(op.httpx, "AsyncClient", lambda *a, **k: _FakeClient())

    provider = op.OpenAIProvider(model="gpt-4o", api_key="sk-test")
    out = []
    async for piece in provider.chat_stream([{"role": "user", "content": "hi"}]):
        out.append(piece)
    assert "".join(out) == "Hello there"


@pytest.mark.asyncio
async def test_adapter_chat_stream_passthrough(monkeypatch):
    from arslan.llm.adapter import LLMAdapter

    adapter = LLMAdapter("stub-unknown", "x", api_key="sk")  # falls back to OpenAIProvider

    async def _fake_stream(messages, tools=None, temperature=0.7):
        for token in ["a", "b", "c"]:
            yield token

    monkeypatch.setattr(adapter._provider, "chat_stream", _fake_stream)
    out = []
    async for piece in adapter.chat_stream("sys", "user"):
        out.append(piece)
    assert out == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# S3-M3 Task 2: stream loops collect REAL usage; estimate only as fallback
# ---------------------------------------------------------------------------


def _patch_openai_stream(monkeypatch, handler):
    """Patch op.httpx.AsyncClient so client.stream() is served by *handler*.

    handler(payload) -> response object (with raise_for_status + aiter_lines).
    Returns the list of captured request payloads (one per stream attempt).
    """
    import arslan.llm.providers.openai_provider as op

    calls: list[dict] = []

    class _Ctx:
        def __init__(self, payload):
            self._payload = payload

        async def __aenter__(self):
            return handler(self._payload)

        async def __aexit__(self, *exc):
            return False

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, **kwargs):
            # Snapshot: the provider reuses (and mutates) the payload dict on retry.
            calls.append(copy.deepcopy(kwargs["json"]))
            return _Ctx(kwargs["json"])

    monkeypatch.setattr(op.httpx, "AsyncClient", lambda *a, **k: _Client())
    return calls


class _SSEResponse:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FailingResponse:
    def __init__(self, status_code):
        self._status = status_code

    def raise_for_status(self):
        req = httpx.Request("POST", "http://test/chat/completions")
        raise httpx.HTTPStatusError(
            f"{self._status}", request=req,
            response=httpx.Response(self._status, request=req),
        )

    async def aiter_lines(self):  # pragma: no cover — never reached after raise
        yield ""


_OPENAI_USAGE_TAIL_SSE = [
    'data: {"choices":[{"delta":{"content":"Hello"}}],"usage":null}',
    'data: {"choices":[{"delta":{"content":" there"}}],"usage":null}',
    'data: {"choices":[],'
    '"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}',
    "data: [DONE]",
]

_OPENAI_NO_TAIL_SSE = [
    'data: {"choices":[{"delta":{"content":"Hello"}}]}',
    "data: [DONE]",
]


@pytest.mark.asyncio
async def test_openai_stream_sends_include_usage_and_captures_tail(monkeypatch):
    """Request body gains stream_options.include_usage; trailing usage frame is captured."""
    import arslan.llm.providers.openai_provider as op

    calls = _patch_openai_stream(monkeypatch, lambda payload: _SSEResponse(_OPENAI_USAGE_TAIL_SSE))
    provider = op.OpenAIProvider(model="gpt-4o", api_key="sk-test")
    out = [p async for p in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert "".join(out) == "Hello there"
    assert calls[0]["stream_options"] == {"include_usage": True}
    assert provider._last_stream_usage == {"tokens_in": 10, "tokens_out": 5}


@pytest.mark.asyncio
async def test_openai_stream_missing_usage_tail_leaves_none(monkeypatch):
    """OpenAI-compat servers that never send the usage frame: no capture, no crash."""
    import arslan.llm.providers.openai_provider as op

    _patch_openai_stream(monkeypatch, lambda payload: _SSEResponse(_OPENAI_NO_TAIL_SSE))
    provider = op.OpenAIProvider(model="gpt-4o", api_key="sk-test")
    out = [p async for p in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert "".join(out) == "Hello"
    assert provider._last_stream_usage is None


@pytest.mark.asyncio
async def test_openai_stream_retries_once_without_stream_options_on_400(monkeypatch):
    """A 4xx on the initial response triggers ONE retry without stream_options."""
    import arslan.llm.providers.openai_provider as op

    def handler(payload):
        if "stream_options" in payload:
            return _FailingResponse(400)
        return _SSEResponse(_OPENAI_NO_TAIL_SSE)

    calls = _patch_openai_stream(monkeypatch, handler)
    provider = op.OpenAIProvider(model="gpt-4o", api_key="sk-test")
    out = [p async for p in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert "".join(out) == "Hello"
    assert len(calls) == 2
    assert "stream_options" in calls[0]
    assert "stream_options" not in calls[1]
    assert provider._last_stream_usage is None  # retry had no usage tail -> estimate path


@pytest.mark.asyncio
async def test_openai_stream_5xx_is_not_retried(monkeypatch):
    """Only 4xx (unknown-param rejection) gets the no-stream_options retry."""
    import arslan.llm.providers.openai_provider as op

    calls = _patch_openai_stream(monkeypatch, lambda payload: _FailingResponse(500))
    provider = op.OpenAIProvider(model="gpt-4o", api_key="sk-test")
    with pytest.raises(httpx.HTTPStatusError):
        _ = [p async for p in provider.chat_stream([{"role": "user", "content": "hi"}])]
    assert len(calls) == 1


_ANTHROPIC_SSE = (
    'data: {"type":"message_start",'
    '"message":{"usage":{"input_tokens":25,"output_tokens":1}}}\n\n'
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"He"}}\n\n'
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"llo"}}\n\n'
    'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
    '"usage":{"output_tokens":12}}\n\n'
    'data: {"type":"message_stop"}\n\n'
)


@pytest.mark.asyncio
async def test_anthropic_stream_captures_usage():
    """input_tokens from message_start; output_tokens from message_delta (cumulative)."""
    from arslan.llm.providers.anthropic_provider import AnthropicProvider

    def handler(request):
        return httpx.Response(200, text=_ANTHROPIC_SSE,
                              headers={"content-type": "text/event-stream"})

    p = AnthropicProvider(model="claude-sonnet-5", api_key="k",
                          transport=httpx.MockTransport(handler))
    out = [c async for c in p.chat_stream([{"role": "user", "content": "hi"}])]

    assert "".join(out) == "Hello"
    assert p._last_stream_usage == {"tokens_in": 25, "tokens_out": 12}


@pytest.mark.asyncio
async def test_anthropic_stream_missing_usage_leaves_none():
    from arslan.llm.providers.anthropic_provider import AnthropicProvider

    sse = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n'

    def handler(request):
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    p = AnthropicProvider(model="claude-sonnet-5", api_key="k",
                          transport=httpx.MockTransport(handler))
    out = [c async for c in p.chat_stream([{"role": "user", "content": "hi"}])]
    assert "".join(out) == "Hi"
    assert p._last_stream_usage is None


_GEMINI_SSE = (
    'data: {"candidates":[{"content":{"parts":[{"text":"He"}]}}]}\n\n'
    'data: {"candidates":[{"content":{"parts":[{"text":"llo"}]}}],'
    '"usageMetadata":{"promptTokenCount":7,"candidatesTokenCount":3,"totalTokenCount":10}}\n\n'
)


@pytest.mark.asyncio
async def test_gemini_stream_captures_usage_tail():
    """Trailing usageMetadata (promptTokenCount/candidatesTokenCount) is captured."""
    from arslan.llm.providers.gemini_provider import GeminiProvider

    def handler(request):
        return httpx.Response(200, text=_GEMINI_SSE,
                              headers={"content-type": "text/event-stream"})

    p = GeminiProvider(model="gemini-2.5-flash", api_key="k",
                       transport=httpx.MockTransport(handler))
    out = [c async for c in p.chat_stream([{"role": "user", "content": "hi"}])]

    assert "".join(out) == "Hello"
    assert p._last_stream_usage == {"tokens_in": 7, "tokens_out": 3}


@pytest.mark.asyncio
async def test_gemini_stream_missing_usage_leaves_none():
    from arslan.llm.providers.gemini_provider import GeminiProvider

    sse = 'data: {"candidates":[{"content":{"parts":[{"text":"Hi"}]}}]}\n\n'

    def handler(request):
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    p = GeminiProvider(model="gemini-2.5-flash", api_key="k",
                       transport=httpx.MockTransport(handler))
    out = [c async for c in p.chat_stream([{"role": "user", "content": "hi"}])]
    assert "".join(out) == "Hi"
    assert p._last_stream_usage is None


@pytest.mark.asyncio
async def test_adapter_stream_reports_real_usage_once():
    """End-to-end: provider captured real usage -> sink gets REAL in/out, total reported
    exactly once (25+12=37, not 37 + an estimate double-report)."""
    from arslan.llm.adapter import LLMAdapter
    from arslan.llm.providers.anthropic_provider import AnthropicProvider

    def handler(request):
        return httpx.Response(200, text=_ANTHROPIC_SSE,
                              headers={"content-type": "text/event-stream"})

    a = LLMAdapter.__new__(LLMAdapter)
    a.provider_name = "anthropic"
    a.model = "claude-sonnet-5"
    a.api_key = "k"
    a._provider = AnthropicProvider(model="claude-sonnet-5", api_key="k",
                                    transport=httpx.MockTransport(handler))

    with usage_sink.collecting():
        out = [c async for c in a.chat_stream("sys", "hi")]
        assert "".join(out) == "Hello"
        assert usage_sink.total() == 37
        d = usage_sink.detail()
        assert d["tokens_in"] == 25
        assert d["tokens_out"] == 12
        assert d["model"] == "claude-sonnet-5"
        assert d["provider"] == "anthropic"


@pytest.mark.asyncio
async def test_adapter_stream_estimate_fallback_when_no_usage_captured():
    """No usage frame -> unchanged behaviour: estimated total, detail tokens None."""
    from arslan.llm.adapter import LLMAdapter

    adapter = LLMAdapter("stub-unknown", "x", api_key="sk")

    async def _fake_stream(messages, tools=None, temperature=0.7):
        for token in ["ab", "cd"]:
            yield token

    adapter._provider.chat_stream = _fake_stream  # type: ignore[method-assign]

    with usage_sink.collecting():
        out = [c async for c in adapter.chat_stream("sys", "user")]
        assert out == ["ab", "cd"]
        assert usage_sink.total() > 0  # estimate reported
        d = usage_sink.detail()
        assert d["tokens_in"] is None
        assert d["tokens_out"] is None
