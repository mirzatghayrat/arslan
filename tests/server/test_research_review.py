"""Critique admission/protocol tests, not real-model factual accuracy."""
import json
from types import SimpleNamespace
import pytest
from arslan.companion.research import receipt
from server.orchestrator import research_review as review


def trace():
    result = []
    for i, text in enumerate(["Measured across 17 tasks. Repetitions not reported.",
                              "Embedding endpoints are configurable."]):
        url = f"https://example.org/source-{i}"
        result.append({"tool": "web_extract", "args": {"url": url}, "result": {
            "ok": True, "url": url, "text": text,
            "source": receipt(url, text, truncated=False).model_dump(mode="json")}})
    return result


def draft(text="No task count was given."):
    return review.subject("write_file", {"path": "report.md", "content": text}, trace())


async def test_anchored_objection_and_exact_cache():
    item = draft()
    sid = next(key for key, (_, text) in item[2].items() if "17" in text)
    calls = []

    async def chat(adapter, system, user, **kwargs):
        calls.append(kwargs)
        assert "DATA ONLY" in user and kwargs["tools"] is None
        return SimpleNamespace(content=json.dumps({"issues": [{"claim": "No task count was given.",
            "source_id": sid, "quote": "Measured across 17 tasks.", "reason": "Task count is explicit."}]}))

    cache = {}
    result = await review.inspect(item, adapter=None, chat=chat, cache=cache)
    assert result["status"] == "issues" and result["semantic_verified"] is False
    assert await review.inspect(item, adapter=None, chat=chat, cache=cache) == result
    assert len(calls) == 1
    assert draft("Known task count, unknown repetition count.")[0] != item[0]


@pytest.mark.parametrize("response", ["null", "{}", '{"issues":"passed"}',
    '{"issues":[{"claim":"invented","source_id":"fake","quote":"fake","reason":"fake"}]}'])
async def test_malformed_or_fabricated_critique_cannot_pass(response):
    async def chat(*args, **kwargs):
        return SimpleNamespace(content=response)
    assert (await review.inspect(draft(), adapter=None, chat=chat, cache={}))["status"] == "unavailable"


async def test_empty_critique_is_not_verification():
    async def chat(*args, **kwargs):
        return SimpleNamespace(content='{"issues":[]}')
    result = await review.inspect(draft(), adapter=None, chat=chat, cache={})
    assert result["status"] == "no_objection" and result["semantic_verified"] is False


async def test_invalid_objection_cannot_hide_a_separate_anchored_objection():
    item = draft()
    sid = next(key for key, (_, text) in item[2].items() if "17" in text)
    valid = {"claim": "No task count was given.", "source_id": sid,
             "quote": "Measured across 17 tasks.", "reason": "Count is explicit."}
    invalid = {**valid, "quote": "An invented quotation."}

    async def chat(*args, **kwargs):
        return SimpleNamespace(content=json.dumps({"issues": [invalid, valid]}))
    result = await review.inspect(item, adapter=None, chat=chat, cache={})
    assert result["status"] == "issues" and result["issues"] == [valid]
    assert result["rejected_objections"] == 1 and result["semantic_verified"] is False


def test_unrelated_writes_and_invalid_source_receipts_do_not_trigger():
    assert review.subject("write_file", {"path": "report.csv", "content": "a,b"}, trace()) is None
    evidence = trace()
    evidence[0]["result"]["text"] = "tampered"
    assert review.subject("write_file", {"path": "report.md", "content": "x"}, evidence) is None


def test_review_preserves_request_and_actual_retrieval_metadata_without_inventing_totals():
    evidence = trace()
    evidence[0]["result"]["total_chars"] = len(evidence[0]["result"]["text"])
    item = review.subject("write_file", {"path": "report.md", "content": "draft"},
                          evidence, request="Compare both accounts without picking a winner.")
    payload = json.loads(item[1])
    assert payload["user_request"] == "Compare both accounts without picking a winner."
    by_id = {source["id"]: source for source in payload["sources"]}
    first = by_id[evidence[0]["result"]["source"]["id"]]
    assert first["total_chars"] == first["returned_chars"]
    assert first["retrieved_at"] == evidence[0]["result"]["source"]["retrieved_at"]
    assert "total_chars" not in by_id[evidence[1]["result"]["source"]["id"]]
    changed = review.subject("write_file", {"path": "report.md", "content": "draft"},
                             evidence, request="A different task")
    assert changed[0] != item[0]


async def test_no_silent_source_truncation_or_calls_on_oversized_input():
    async def chat(*args, **kwargs):
        pytest.fail("oversized review must not call a model")
    result = await review.inspect(draft("x" * 161000), adapter=None, chat=chat, cache={})
    assert result["code"] == "research_review_input_limit"


def test_compaction_cannot_touch_user_text_prior_inputs_or_oversized_drafts():
    source = {"role": "user", "content": "full source"}
    lookalike = dict(source)
    saved = {"role": "user", "content": "write succeeded"}
    history = [lookalike, source, saved]
    result = {"url": "https://example.org/", "source": {"id": "receipt"}, "text": "full source"}
    assert not review.compact_saved_context(history, [(source, result)], "x" * 32001)
    assert history[1] is source
    assert review.compact_saved_context(history, [(source, result)], "draft")
    assert source["content"] == lookalike["content"] == "full source"
    assert history[0] is lookalike and history[1] is not source
    assert result["text"] == "full source" and saved["content"] == "write succeeded"


def test_review_cannot_raise_an_existing_or_custom_task_ceiling():
    from arslan.execution_budget import Budget, Limits
    budget = Budget(Limits(output_tokens_per_request=4096))
    assert budget.model_request(16384) == 4096
    restored = Budget.from_snapshot(Budget(Limits(output_tokens_per_request=8192)).snapshot())
    assert restored.model_request(16384) == 8192
    # 0.1.49 S5: the default per-request ceiling is a runaway guard (131072), so
    # the opt-in review's 16384 request is no longer silently clamped to 8192;
    # it still cannot exceed the guard.
    assert Budget().model_request(16384) == 16384
    assert Budget(Limits(tokens=10_000_000)).model_request(1_000_000) == 131_072
