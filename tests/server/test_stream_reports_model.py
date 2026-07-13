"""chat_stream must report model/provider via usage_sink.report_detail, just like
chat does, so spawn runs streamed to the UI still surface a model on the detail page
(tokens stay estimated for the stream path)."""
from __future__ import annotations

from arslan.llm import usage_sink
from arslan.llm.adapter import LLMAdapter


async def test_chat_stream_reports_model():
    class _Provider:
        def build_messages(self, system, user, history):
            return []

        async def chat_stream(self, messages, tools=None, temperature=0.7):
            for chunk in ["a", "b"]:
                yield chunk

    adapter = LLMAdapter.__new__(LLMAdapter)
    adapter._provider = _Provider()
    adapter.model = "claude-x"
    adapter.provider_name = "anthropic"

    with usage_sink.collecting():
        async for _ in adapter.chat_stream("sys", "hi"):
            pass
        d = usage_sink.detail()
    assert d["model"] == "claude-x"
    assert d["provider"] == "anthropic"
