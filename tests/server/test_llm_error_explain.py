"""Turn a provider's billing/quota refusal into something the user can act on.

Same doctrine as vision_errors: DELIBERATELY NARROW. Mislabelling an unrelated
fault sends someone off topping up an account that was never the problem, which
is worse than showing the raw error. Anything unrecognised passes through
untouched.

The case that prompted this: OpenRouter answered 402 with a wall of JSON —
"requires more credits, or fewer max_tokens… You requested up to 65536 tokens,
but can only afford 64381" — rendered verbatim in the chat bubble, key-id URL
and all. The user could not tell whether their account was empty, their key was
capped, or Arslan was broken.
"""
from server.orchestrator import llm_errors


def test_openrouter_key_limit_is_named_as_a_key_cap():
    raw = ('Client error \'402 Payment Required\' for url '
           '\'https://openrouter.ai/api/v1/chat/completions\' '
           '{"error":{"message":"This request requires more credits, or fewer max_tokens. '
           'You requested up to 65536 tokens, but can only afford 64381.","code":402,'
           '"metadata":{"limit_source":"openrouter_key_limit",'
           '"remedy_hint":"Raise or remove this API key\'s usage limit."}}}')
    out = llm_errors.explain(raw)
    assert out is not None
    # says WHICH limit (the key's, not the account's) and what to do
    assert "key" in out.lower()
    assert "openrouter.ai" in out               # where to go
    # and does not just re-dump the JSON at the user
    assert "limit_source" not in out
    assert len(out) < 400


def test_plain_402_without_key_metadata_is_a_balance_message():
    raw = ("Client error '402 Payment Required' for url "
           "'https://api.example.com/v1/chat/completions' "
           '{"error":{"message":"Insufficient credits","code":402}}')
    out = llm_errors.explain(raw)
    assert out is not None and "402" not in out   # human words, not a status code
    assert "credit" in out.lower() or "余额" in out or "balance" in out.lower()


def test_401_is_a_key_problem_not_a_money_problem():
    raw = "Client error '401 Unauthorized' for url 'https://api.openai.com/v1/chat/completions'"
    out = llm_errors.explain(raw)
    assert out is not None
    low = out.lower()
    assert "key" in low
    assert "credit" not in low and "余额" not in out   # never mislabel auth as billing


def test_429_is_rate_limiting_and_says_wait():
    raw = "Client error '429 Too Many Requests' for url 'https://api.deepseek.com/chat/completions'"
    out = llm_errors.explain(raw)
    assert out is not None
    assert "rate" in out.lower() or "too many" in out.lower() or "稍" in out


def test_unrecognised_errors_pass_through_untouched():
    """The narrowness guarantee: no invented diagnosis."""
    for raw in ("Connection refused", "some novel provider failure",
                "Client error '418 I am a teapot'"):
        assert llm_errors.explain(raw) is None


def test_context_length_is_explained_as_length_never_as_money():
    """A too-long conversation and an empty wallet need opposite remedies, and
    the token counts in a context error read exactly like the ones in a billing
    error — so this must be classified, not merely 'not misclassified'."""
    raw = ('{"error":{"message":"This model\'s maximum context length is 128000 tokens, '
           'however you requested 140000 tokens","code":"context_length_exceeded"}}')
    out = llm_errors.explain(raw)
    assert out is not None, "a context overflow must be explained, not passed through"
    assert "上下文" in out or "context" in out.lower()
    assert "余额" not in out and "credit" not in out.lower()
