from arslan.llm import usage_sink


def test_report_outside_context_is_noop():
    usage_sink.report(50)  # must not raise
    assert usage_sink.total() == 0


def test_collecting_accumulates_and_isolates():
    with usage_sink.collecting():
        usage_sink.report(10)
        usage_sink.report(5)
        assert usage_sink.total() == 15
    # context exited → fresh
    assert usage_sink.total() == 0


def test_estimate_tokens_cjk_aware():
    # 4 CJK chars ≈ 4 tokens; 8 ascii chars ≈ 2 tokens
    assert usage_sink.estimate_tokens("帮我写个") == 4
    assert usage_sink.estimate_tokens("abcdefgh") == 2
    assert usage_sink.estimate_tokens("", None) == 0
