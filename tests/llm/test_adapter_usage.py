
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


async def test_chat_reports_zero_when_provider_says_zero():
    a = _adapter({"total_tokens": 0})
    with usage_sink.collecting():
        await a.chat("sys", "user")
        assert usage_sink.total() == 0


# --- S3-M3 Task 5 (S1 fold-in): total normalization -------------------------
# gemini's non-stream usage carries totalTokenCount, anthropic carries only
# input/output — both are REAL numbers and must never fall through to the estimate.


async def test_chat_reports_gemini_total_token_count():
    a = _adapter({"promptTokenCount": 100, "candidatesTokenCount": 40,
                  "totalTokenCount": 140})
    with usage_sink.collecting():
        await a.chat("sys", "user")
        assert usage_sink.total() == 140


async def test_chat_sums_in_out_when_no_total_key():
    # anthropic shape: input/output only, no total field at all
    a = _adapter({"input_tokens": 70, "output_tokens": 30})
    with usage_sink.collecting():
        await a.chat("sys", "user")
        assert usage_sink.total() == 100


async def test_chat_real_zero_prompt_tokens_stays_real_not_estimated():
    # Review S2: a REAL 0 must not be laundered to None by an `or` chain —
    # the bucket keeps real 0/5 figures and is NOT marked estimated.
    a = _adapter({"prompt_tokens": 0, "completion_tokens": 5})
    with usage_sink.collecting():
        await a.chat("sys", "user")
        detail = usage_sink.detail()
        assert usage_sink.total() == 5
    [bucket] = detail["buckets"]
    assert (bucket["tokens_in"], bucket["tokens_out"]) == (0, 5)
    assert bucket["estimated"] is False
    assert (detail["tokens_in"], detail["tokens_out"]) == (0, 5)
