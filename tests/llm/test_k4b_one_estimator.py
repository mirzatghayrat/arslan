"""K4b: one token estimator (master plan K4 ⑥).

Before there were two: `usage_sink.estimate_tokens` (the adapter's no-usage fallback) counted only Han
characters as one token each, while `context_budget.estimate_tokens` (memory, personal context, turn
tools) also counted kana and Hangul. A Japanese or Korean reply with no usage frame was charged about a
quarter of what the context budget said it was. Only `context_budget.estimate_tokens` is left.
"""
import ast
from pathlib import Path

from arslan import context_budget
from arslan.llm import usage_sink
from tests.llm.test_adapter_usage import _adapter

ROOT = Path(__file__).resolve().parents[2]


def test_there_is_exactly_one_token_estimator():
    found = []
    for folder in ("arslan", "server"):
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "estimate_tokens":
                    found.append(path.relative_to(ROOT).as_posix())
    assert found == ["arslan/context_budget.py"]


async def test_the_no_usage_fallback_counts_kana_as_the_context_budget_does():
    a = _adapter({})                                   # the provider sent no usage
    with usage_sink.collecting():
        await a.chat("", "こんにちは")                     # the fake answers "hi there"
        assert usage_sink.total() == 5 + len("hi there") // 4


async def test_the_streamed_fallback_counts_hangul_too():
    a = _adapter({})
    with usage_sink.collecting():
        assert [p async for p in a.chat_stream("", "안녕하세요")] == ["ab", "cd"]
        assert usage_sink.total() == 5 + len("abcd") // 4


def test_an_image_block_counts_as_eight_hundred_tokens_and_nothing_raises():
    image = {"type": "image", "source": {"type": "base64", "data": "A" * 40_000}}
    assert context_budget.estimate_tokens("S", [image]) == context_budget.estimate_tokens("S") + 800
    assert context_budget.estimate_tokens("x", None, [{"type": "text", "text": "abcd"}], 7) == 1
    assert context_budget.estimate_tokens("a" * 400) == 100 and context_budget.estimate_tokens("中" * 10) == 10
