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
    """The narrowness guarantee: no invented diagnosis.

    "Connection refused" USED to be one of these examples and was moved out on
    2026-08-24, not because the guarantee weakened but because that string
    stopped being unrecognised: transport failures are now a named class, and
    "the request never left" is a real diagnosis rather than an invented one.
    The examples below are still genuinely unclassified.
    """
    for raw in ("some novel provider failure",
                "Client error '418 I am a teapot'",
                "the model returned an empty choices array"):
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


# ── the three faults that shipped unexplained, all measured on 2026-08-24 ──────
#
# Every `raw` below is a VERBATIM string captured from a live probe against a
# real key, not a plausible-looking invention. That matters here more than usual:
# this module matches on provider prose, and prose I made up would produce a
# matcher that fits nothing real.

KEY_LIMIT_403 = (
    "Client error '403 Forbidden' for url "
    "'https://openrouter.ai/api/v1/chat/completions'\n"
    '{"error":{"message":"Key limit exceeded (total limit). Manage it using '
    'https://openrouter.ai/workspaces/default","code":403}}'
)
REGION_403 = (
    "Client error '403 Forbidden' for url "
    "'https://openrouter.ai/api/v1/chat/completions'\n"
    '{"error":{"message":"This model is not available in your region.","code":403}}'
)
TLS_FAILURE = (
    "<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in "
    "violation of protocol (_ssl.c:1016)>"
)


def test_a_key_cap_is_recognised_when_the_provider_says_it_with_403():
    """The sentence for this already existed and was UNREACHABLE.

    It was nested inside the 402 branch, and OpenRouter reports the same fault
    as 403 — so a user whose key had hit its cap got the raw JSON, and the one
    answer written for them could never be shown.
    """
    out = llm_errors.explain(KEY_LIMIT_403)
    assert out is not None
    assert "上限" in out
    # The distinction the sentence exists to draw: capped key ≠ empty account.
    assert "余额" in out


def test_a_region_block_is_not_reported_as_a_key_or_money_problem():
    out = llm_errors.explain(REGION_403)
    assert out is not None
    assert "地区" in out
    # The wrong remedies, named so a rewrite cannot quietly reintroduce them.
    assert "充值" not in out
    assert "换一把" not in out


def test_a_region_block_and_a_key_cap_do_not_collapse_into_one_message():
    # Same status code, same provider, same shape of JSON — and different
    # remedies. If these two ever return the same sentence, one of them is lying.
    assert llm_errors.explain(REGION_403) != llm_errors.explain(KEY_LIMIT_403)


def test_a_transport_failure_says_it_never_reached_the_provider():
    out = llm_errors.explain(TLS_FAILURE)
    assert out is not None
    assert "没能连上" in out
    # The whole point: this must not read as a key fault. That misreading cost
    # a real debugging session — three rounds spent testing a healthy key.
    assert "key 的问题" in out or "不是 key" in out


def test_a_transport_failure_is_not_mistaken_for_auth_when_it_mentions_401():
    # A proxy error page can carry a stray status number. Transport is checked
    # first precisely so a number inside an unrelated body cannot outrank the
    # fact that nothing was ever sent.
    raw = "ConnectError: proxy returned 401 while establishing tunnel to api.openai.com:443"
    out = llm_errors.explain(raw)
    assert out is not None and "没能连上" in out


def test_a_real_auth_refusal_is_still_an_auth_refusal():
    # The regression guard for the ordering above: a genuine 401 FROM the
    # provider must keep its own message.
    raw = ("Client error '401 Unauthorized' for url "
           "'https://openrouter.ai/api/v1/chat/completions'\n"
           '{"error":{"message":"User not found.","code":401}}')
    out = llm_errors.explain(raw)
    assert out is not None and "API key" in out and "没能连上" not in out


def test_a_plain_402_is_still_a_balance_message_not_a_key_cap():
    raw = ('{"error":{"message":"Insufficient Balance","type":"unknown_error",'
           '"code":"invalid_request_error"}}')
    out = llm_errors.explain(raw)
    assert out is not None and "余额不足" in out
