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


# --- S3-M3 Task 1: per-(model, provider) buckets, primary-bucket attribution ---


def test_detail_buckets_two_models_primary_by_total_tokens():
    """Mixed-model turn (tool-loop model + synthesis adapter) must NOT be
    attributed wholesale to the last model that reported — primary = biggest bucket."""
    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=300, tokens_out=100, model="model-a", provider="openai")
        usage_sink.report_detail(tokens_in=50, tokens_out=20, model="model-b", provider="anthropic")
        d = usage_sink.detail()
    # totals across buckets
    assert d["tokens_in"] == 350 and d["tokens_out"] == 120
    # primary bucket (most total tokens) wins attribution — NOT last-wins (model-b)
    assert d["model"] == "model-a" and d["provider"] == "openai"
    # per-bucket breakdown
    assert len(d["buckets"]) == 2
    assert {"model": "model-a", "provider": "openai", "tokens_in": 300, "tokens_out": 100} in d["buckets"]
    assert {"model": "model-b", "provider": "anthropic", "tokens_in": 50, "tokens_out": 20} in d["buckets"]


def test_detail_same_model_accumulates_into_one_bucket():
    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=10, tokens_out=20, model="gpt-x", provider="openai")
        usage_sink.report_detail(tokens_in=5, tokens_out=7, model="gpt-x", provider="openai")
        d = usage_sink.detail()
    assert d["buckets"] == [
        {"model": "gpt-x", "provider": "openai", "tokens_in": 15, "tokens_out": 27},
    ]
    assert d["tokens_in"] == 15 and d["tokens_out"] == 27
    assert d["model"] == "gpt-x" and d["provider"] == "openai"


def test_detail_totals_none_when_any_bucket_estimated():
    """A stream-path report (None in/out) marks its bucket estimated — totals must
    go None (honest: never mix estimates into real numbers), while the real
    bucket keeps its real per-bucket figures."""
    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=300, tokens_out=100, model="model-a", provider="openai")
        usage_sink.report_detail(tokens_in=None, tokens_out=None, model="model-b", provider="ollama")
        d = usage_sink.detail()
    assert d["tokens_in"] is None and d["tokens_out"] is None
    a = next(b for b in d["buckets"] if b["model"] == "model-a")
    assert a["tokens_in"] == 300 and a["tokens_out"] == 100
    b = next(b for b in d["buckets"] if b["model"] == "model-b")
    assert b["tokens_in"] is None and b["tokens_out"] is None
    # primary attribution still model-a (400 > 0)
    assert d["model"] == "model-a" and d["provider"] == "openai"


def test_primary_helper():
    with usage_sink.collecting():
        assert usage_sink.primary() is None  # active scope, no reports yet
        usage_sink.report_detail(tokens_in=1, tokens_out=2, model="m", provider="p")
        usage_sink.report_detail(tokens_in=900, tokens_out=1, model="big", provider="q")
        p = usage_sink.primary()
    assert p == {"model": "big", "provider": "q", "tokens_in": 900, "tokens_out": 1}
    assert usage_sink.primary() is None  # no context


def test_detail_empty_shapes_include_buckets_key():
    # outside any context
    assert usage_sink.detail() == {
        "tokens_in": None, "tokens_out": None, "model": None, "provider": None, "buckets": [],
    }
    # inside a fresh context with no reports
    with usage_sink.collecting():
        d = usage_sink.detail()
    assert d["buckets"] == [] and d["model"] is None and d["tokens_in"] is None
