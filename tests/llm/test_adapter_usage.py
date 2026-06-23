import pytest

from arslan.llm import usage_sink
from arslan.llm.adapter import LLMAdapter
from arslan.models import LLMResponse


class _FakeProvider:
    def __init__(self, usage):
        self._usage = usage

    def build_messages(self, system, user, history):
        return [{"role": "user", "content": user}]

    async def chat(self, messages, tools=None, temperature=0.7):
        return LLMResponse(content="hi there", usage=self._usage)

    async def chat_stream(self, messages, tools=None, temperature=0.7):
        for piece in ["ab", "cd"]:
            yield piece


def _adapter(usage):
    a = LLMAdapter.__new__(LLMAdapter)
    a.provider_name = "openai"
    a.model = "x"
    a.api_key = ""
    a._provider = _FakeProvider(usage)
    return a


async def test_chat_reports_provider_usage_total():
    a = _adapter({"total_tokens": 123})
    with usage_sink.collecting():
        await a.chat("sys", "user")
        assert usage_sink.total() == 123


async def test_chat_estimates_when_no_usage():
    a = _adapter({})  # provider returned no usage
    with usage_sink.collecting():
        await a.chat("sys", "userrr")
        assert usage_sink.total() > 0


async def test_chat_stream_estimates_from_accumulated():
    a = _adapter({})
    with usage_sink.collecting():
        out = [p async for p in a.chat_stream("sys", "user")]
        assert out == ["ab", "cd"]
        assert usage_sink.total() > 0
