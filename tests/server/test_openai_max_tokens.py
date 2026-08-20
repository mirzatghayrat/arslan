"""The OpenAI-compatible payload declares an output budget.

WHY (field report, v0.1.25): the body carried no `max_tokens`, so OpenRouter
reserved the MODEL's ceiling — 65536 for Claude — and refused a key that could
still afford 64381. The user had budget left and could not spend it, because we
never said how much we intended to use. Anthropic's own provider has always
sent one (anthropic_provider.DEFAULT_MAX_TOKENS); this path simply never did.
"""
from arslan.llm.providers.openai_provider import OpenAIProvider


def _payload(**kw):
    p = OpenAIProvider(api_key="k", model="m", **kw)
    return p._payload([{"role": "user", "content": "hi"}], None, 0.7)


def test_payload_declares_max_tokens():
    assert _payload()["max_tokens"] == OpenAIProvider.DEFAULT_MAX_TOKENS


def test_the_default_is_a_working_budget_not_a_model_ceiling():
    """Large enough for real answers, far below the 64K ceiling whose blind
    reservation caused the 402."""
    v = OpenAIProvider.DEFAULT_MAX_TOKENS
    assert 2048 <= v <= 16384


def test_an_explicit_budget_overrides_the_default():
    assert _payload(max_tokens=1000)["max_tokens"] == 1000


def test_tools_and_messages_are_untouched_by_the_addition():
    p = OpenAIProvider(api_key="k", model="m")
    tools = [{"type": "function", "function": {"name": "x"}}]
    body = p._payload([{"role": "user", "content": "hi"}], tools, 0.3)
    assert body["tools"] == tools
    assert body["temperature"] == 0.3
    assert body["messages"][0]["role"] == "user"
