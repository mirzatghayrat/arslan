"""LLM streaming tests for the OpenAI-compatible provider and adapter."""
import pytest

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
