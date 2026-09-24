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


async def test_no_silent_source_truncation_or_calls_on_oversized_input():
    async def chat(*args, **kwargs):
        pytest.fail("oversized review must not call a model")
    result = await review.inspect(draft("x" * 161000), adapter=None, chat=chat, cache={})
    assert result["code"] == "research_review_input_limit"


async def test_native_loop_blocks_bad_draft_then_dispatches_only_revised_bytes(monkeypatch):
    from server.orchestrator import tool_loop
    from tests.server.test_native_loop import _NativeAdapter, _LLMResp, _tc
    evidence = trace()
    sid = evidence[0]["result"]["source"]["id"]
    adapter = _NativeAdapter([
        _LLMResp(tool_calls=[_tc("web_extract", entry["args"]) for entry in evidence]),
        _LLMResp(tool_calls=[_tc("write_file", {"path": "report.md", "content": "No task count was given."})]),
        _LLMResp(content=json.dumps({"issues": [{"claim": "No task count was given.",
            "source_id": sid, "quote": "Measured across 17 tasks.", "reason": "Count is present."}]})),
        _LLMResp(tool_calls=[_tc("write_file", {"path": "report.md", "content": "17 tasks; repetitions unknown."})]),
        _LLMResp(content='{"issues":[]}'),
        _LLMResp(content="Report saved. Model critique is not proof of factual accuracy."),
    ])
    writes = []
    permission = object()

    async def resolve():
        return [{"key": "web_extract", "description": "read"}, {"key": "write_file", "description": "write"}]

    async def dispatch(name, args, assistant_content, **kwargs):
        assert kwargs["confirm_workspace_write"] is permission
        if name == "web_extract":
            result = next(e["result"] for e in evidence if e["args"] == args)
        else:
            writes.append(args["content"])
            result = {"ok": True, "external": False}
        return tool_loop._record_tool_result(name, args, result, kwargs["emit"],
            kwargs["tool_trace"], assistant_content, kwargs["convo"])

    monkeypatch.setattr(tool_loop, "_dispatch_tool", dispatch)
    result = await tool_loop.run_native(system="s", user_content="Compare sources and save.", history=[],
        emit=lambda _: None, on_chunk=lambda _: None, resolve_tools=resolve,
        adapter_override=adapter, confirm_workspace_write=permission)
    assert writes == ["17 tasks; repetitions unknown."]
    assert any(e["result"].get("code") == "research_draft_review_required" for e in result["tool_trace"])
    assert len(adapter.calls) == 6
    assert adapter.calls[2]["tools"] is None and adapter.calls[4]["tools"] is None


async def test_unavailable_review_stops_without_write_or_paid_retry(monkeypatch):
    from server.orchestrator import tool_loop
    from tests.server.test_native_loop import _NativeAdapter, _LLMResp, _tc
    evidence = trace()
    adapter = _NativeAdapter([
        _LLMResp(tool_calls=[_tc("web_extract", entry["args"]) for entry in evidence]),
        _LLMResp(tool_calls=[_tc("write_file", {"path": "report.md", "content": "draft"})]),
        _LLMResp(content=""),
    ])

    async def resolve():
        return [{"key": "web_extract", "description": "read"}, {"key": "write_file", "description": "write"}]

    async def dispatch(name, args, assistant_content, **kwargs):
        assert name == "web_extract", "unavailable review must not write"
        result = next(e["result"] for e in evidence if e["args"] == args)
        return tool_loop._record_tool_result(name, args, result, kwargs["emit"],
            kwargs["tool_trace"], assistant_content, kwargs["convo"])

    monkeypatch.setattr(tool_loop, "_dispatch_tool", dispatch)
    result = await tool_loop.run_native(system="s", user_content="Compare and save.", history=[],
        emit=lambda _: None, on_chunk=lambda _: None, resolve_tools=resolve, adapter_override=adapter)
    assert result["stop_reason"] == "task_validation_failed"
    assert len(adapter.calls) == 3


def test_critique_mode_is_local_vendor_scoped_and_never_changes_normal_calls():
    from arslan.llm.providers.openai_provider import OpenAIProvider
    from arslan.llm.request_policy import critique_request
    provider = OpenAIProvider("deepseek-v4-flash", base_url="https://api.deepseek.com")
    other = OpenAIProvider("deepseek-v4-flash", base_url="https://example.org")
    assert "thinking" not in provider._payload([], None, 0.7)
    with critique_request():
        assert provider._payload([], None, 0.7)["thinking"] == {"type": "enabled"}
        assert provider._payload([], None, 0.7)["reasoning_effort"] == "low"
        assert "thinking" not in provider._payload([], [{"type": "function"}], 0.7)
        assert "thinking" not in other._payload([], None, 0.7)
    assert "thinking" not in provider._payload([], None, 0.7)
