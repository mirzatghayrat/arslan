from arslan.llm import usage_sink


def test_detail_captures_and_aggregates_usage():
    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=10, tokens_out=20, model="gpt-x", provider="openai")
        usage_sink.report_detail(tokens_in=5, tokens_out=7, model="gpt-x", provider="openai")
        d = usage_sink.detail()
    assert d["tokens_in"] == 15 and d["tokens_out"] == 27
    assert d["model"] == "gpt-x" and d["provider"] == "openai"


def test_detail_empty_when_no_reports():
    with usage_sink.collecting():
        d = usage_sink.detail()
    assert d["tokens_in"] is None and d["model"] is None


def test_report_detail_noop_without_context():
    usage_sink.report_detail(tokens_in=1, tokens_out=1, model="m", provider="p")  # must not raise
    assert usage_sink.detail()["tokens_in"] is None
