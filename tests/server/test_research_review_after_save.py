"""0.1.41 research review: after-save advice, never a gate (task brief A1-A7, A9).

Offline only. Scripted model replies; no real model quality is claimed.
"""
import json

import pytest

from arslan.execution_budget import Budget, Limits, scope
from server.orchestrator import research_review, tool_loop
from server.services import artifact_store
from tests.server.test_native_loop import _LLMResp, _NativeAdapter, _tc
from tests.server.test_research_review import trace

RUN_ID = 7
DRAFT = "No task count was given."
OBJECTION = "Count is present in the source."


class _CritiqueAdapter(_NativeAdapter):
    """A test double whose provider can send a bounded (non-thinking) critique."""

    def supports_bounded_critique(self):
        return True


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "artifacts")
    return tmp_path


async def _run(monkeypatch, adapter, *, enabled=True):
    evidence = trace()
    writes = []

    async def enabled_setting():
        return enabled

    monkeypatch.setattr(tool_loop, "_research_review_enabled", enabled_setting)

    async def resolve():
        return [{"key": k, "description": k} for k in ("web_extract", "write_file")]

    async def dispatch(name, args, assistant_content, **kwargs):
        if name == "web_extract":
            result = next(e["result"] for e in evidence if e["args"] == args)
        else:
            writes.append(args["content"])
            artifact = artifact_store.store_bytes(RUN_ID, args["path"], args["content"].encode())
            result = {"ok": True, "external": False, "path": args["path"], "artifact": artifact}
        return tool_loop._record_tool_result(name, args, result, kwargs["emit"],
                                             kwargs["tool_trace"], assistant_content, kwargs["convo"])

    monkeypatch.setattr(tool_loop, "_dispatch_tool", dispatch)
    events = []
    result = await tool_loop.run_native(system="s", user_content="Compare and save.", history=[],
                                        emit=events.append, on_chunk=lambda _: None, resolve_tools=resolve,
                                        adapter_override=adapter)
    return result, writes, events


def _script(review_reply):
    evidence = trace()
    replies = [
        _LLMResp(tool_calls=[_tc("web_extract", e["args"]) for e in evidence]),
        _LLMResp(tool_calls=[_tc("write_file", {"path": "report.md", "content": DRAFT})]),
        review_reply,
        _LLMResp(content="Report saved."),
    ]
    return [r for r in replies if r is not None]


def _stored_note():
    [artifact] = artifact_store.list_artifacts(RUN_ID)
    return artifact_store.read_review(RUN_ID, artifact["filename"])


async def test_saved_report_is_reviewed_after_the_write_and_the_note_is_stored(monkeypatch, store):
    sid = trace()[0]["result"]["source"]["id"]
    reply = _LLMResp(content=json.dumps({"issues": [{"claim": DRAFT, "source_id": sid,
        "quote": "Measured across 17 tasks.", "reason": OBJECTION}]}))
    adapter = _CritiqueAdapter(_script(reply))
    result, writes, events = await _run(monkeypatch, adapter)

    assert writes == [DRAFT]                      # written once, never replaced by a revision
    assert result["final"] == "Report saved."
    assert result.get("stop_reason") != "task_validation_failed"
    assert len(adapter.calls) == 4                # web, write, ONE critique, final answer
    assert adapter.calls[2]["tools"] is None and "DATA ONLY" in adapter.calls[2]["user"]
    # The writing model never sees the critique: nothing after it mentions the objection.
    assert OBJECTION not in json.dumps(adapter.calls[3], default=str)
    assert not any("review" in e["result"] for e in result["tool_trace"])
    note = _stored_note()
    assert note["status"] == "issues" and note["semantic_verified"] is False
    assert note["issues"][0]["claim"] == DRAFT
    assert note["issues"][0]["source_url"] == "https://example.org/source-0"
    assert any(e.get("type") == "research_review" and e["issues"] == 1 for e in events)


@pytest.mark.parametrize("reply", [
    _LLMResp(content=""),
    _LLMResp(content="null"),
    _LLMResp(content='{"issues":"passed"}'),
    _LLMResp(content='{"issues":[]}', tool_calls=[_tc("write_file", {"path": "x", "content": "y"})]),
])
async def test_an_unusable_review_never_blocks_or_changes_the_task(monkeypatch, store, reply):
    adapter = _CritiqueAdapter(_script(reply))
    result, writes, _ = await _run(monkeypatch, adapter)
    assert writes == [DRAFT]
    assert result["final"] == "Report saved."
    assert result.get("stop_reason") != "task_validation_failed"
    assert len(adapter.calls) == 4                # no paid retry of the critique
    assert _stored_note()["status"] == "unavailable"


async def test_a_raising_review_request_is_recorded_not_propagated(monkeypatch, store):
    class Boom(_CritiqueAdapter):
        async def chat(self, system, user, history=None, tools=None, temperature=0.7):
            if tools is None and "DATA ONLY" in str(user):
                self.calls.append({"tools": None, "user": user})
                raise ValueError("provider rejected the request")
            return await super().chat(system, user, history=history, tools=tools)

    adapter = Boom(_script(None))
    result, writes, _ = await _run(monkeypatch, adapter)
    assert writes == [DRAFT] and result["final"] == "Report saved."
    assert _stored_note()["code"] == "research_review_unavailable"


async def test_setting_off_makes_zero_review_calls(monkeypatch, store):
    async def forbidden(*args, **kwargs):
        pytest.fail("review is off: no critique request may be sent")

    monkeypatch.setattr(research_review, "inspect", forbidden)
    adapter = _CritiqueAdapter(_script(None))
    _, writes, _ = await _run(monkeypatch, adapter, enabled=False)
    assert writes == [DRAFT] and len(adapter.calls) == 3
    assert _stored_note() is None


async def test_provider_that_may_think_gets_no_review_call(monkeypatch, store):
    adapter = _NativeAdapter(_script(None))       # no bounded-critique support
    _, writes, _ = await _run(monkeypatch, adapter)
    assert writes == [DRAFT] and len(adapter.calls) == 3
    assert _stored_note()["code"] == "research_review_unsupported_provider"


def test_budget_check_keeps_room_for_the_task_to_finish():
    raw = "x" * 20_000
    with scope(Budget(Limits(model_requests=32, tokens=128_000))):
        assert research_review.affordable(raw)
    tight = Budget(Limits(model_requests=32, tokens=128_000))
    tight.model_requests = 31                     # the critique would use the last request
    with scope(tight):
        assert not research_review.affordable(raw)
    spent = Budget(Limits(model_requests=32, tokens=128_000))
    spent.tokens = 128_000 - research_review.RESERVE_TOKENS
    with scope(spent):
        assert not research_review.affordable(raw)


async def test_unaffordable_review_is_skipped_without_a_call(monkeypatch, store):
    monkeypatch.setattr(research_review, "affordable", lambda raw: False)
    adapter = _CritiqueAdapter(_script(None))
    _, writes, _ = await _run(monkeypatch, adapter)
    assert writes == [DRAFT] and len(adapter.calls) == 3
    assert _stored_note()["code"] == "research_review_budget_reserved"


def test_prompt_is_scoped_to_absence_and_comparison_claims():
    prompt = research_review.PROMPT
    assert "ONLY absence claims and cross-document comparison claims" in prompt
    assert "Do not object to wording, level of detail, choice of examples, completeness" in prompt
    # The 0.1.40 prompt adjudicated every factual claim; that scope produced most false positives.
    assert "Adjudicate factual support" not in prompt


def test_review_note_is_bound_to_the_exact_snapshot(store):
    first = artifact_store.store_bytes(RUN_ID, "report.md", b"v1")
    assert artifact_store.write_review(first, {"status": "no_objection", "issues": []})
    assert not artifact_store.write_review(first, {"status": "issues", "issues": []})  # exactly once
    assert artifact_store.read_review(RUN_ID, first["filename"])["status"] == "no_objection"
    second = artifact_store.store_bytes(RUN_ID, "report.md", b"v2")
    assert artifact_store.read_review(RUN_ID, second["filename"]) is None
    assert not artifact_store.write_review({**second, "sha256": "0" * 64}, {"status": "issues"})
    assert sorted(a["filename"] for a in artifact_store.list_artifacts(RUN_ID)) == sorted(
        [first["filename"], second["filename"]])
    assert artifact_store.read_review(RUN_ID, "../" + first["filename"]) is None


def test_critique_payloads_disable_thinking_and_stay_short():
    from arslan.llm.providers.anthropic_provider import AnthropicProvider
    from arslan.llm.providers.gemini_provider import GeminiProvider
    from arslan.llm.providers.openai_provider import OpenAIProvider
    from arslan.llm.request_policy import critique_request

    deepseek = OpenAIProvider("deepseek-v4-flash", base_url="https://api.deepseek.com")
    other = OpenAIProvider("some-reasoner", base_url="https://example.org")
    normal = deepseek._payload([], None, 0.7)
    assert "thinking" not in normal and normal["temperature"] == 0.7
    # 0.1.49 S5: official DeepSeek declares 32768 (thinking spends the same cap);
    # the critique below must still be short and thinking-free.
    assert normal["max_tokens"] == 32_768
    with critique_request():
        critique = deepseek._payload([], None, 0.7)
        assert critique["thinking"] == {"type": "disabled"} and "reasoning_effort" not in critique
        assert critique["temperature"] == 0 and critique["max_tokens"] == 2048
        assert "thinking" not in deepseek._payload([], [{"type": "function"}], 0.7)
        assert "thinking" not in other._payload([], None, 0.7)
        anthropic = AnthropicProvider("claude-sonnet-5", api_key="k")._payload([], 0.7)
        assert anthropic["temperature"] == 0 and anthropic["max_tokens"] == 2048
        assert "thinking" not in anthropic
    assert deepseek._payload([], None, 0.7) == normal
    assert deepseek.supports_bounded_critique() and not other.supports_bounded_critique()
    assert AnthropicProvider("claude-sonnet-5", api_key="k").supports_bounded_critique()
    assert not GeminiProvider("gemini-2.5-pro", api_key="k").supports_bounded_critique()


async def test_toggle_defaults_off_and_is_reachable_through_the_settings_api(client, monkeypatch):
    """Drive the real HTTP round-trip: a key on only one schema is silently dropped."""
    from server.db import session as db_session
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)

    r = await client.get("/api/v1/settings")
    assert r.status_code == 200 and r.json()["research_review_enabled"] is False
    assert await tool_loop._research_review_enabled() is False
    r = await client.put("/api/v1/settings", json={"research_review_enabled": True})
    assert r.status_code == 200, r.text
    assert await tool_loop._research_review_enabled() is True
    r = await client.put("/api/v1/settings", json={"research_review_enabled": False})
    assert r.status_code == 200, r.text
    assert await tool_loop._research_review_enabled() is False


async def test_unreadable_setting_fails_closed(monkeypatch):
    from server.db import session as db_session

    def broken():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db_session, "AsyncSessionLocal", broken)
    assert await tool_loop._research_review_enabled() is False


async def test_review_endpoint_serves_the_note_or_none(client, monkeypatch, tmp_path):
    monkeypatch.setattr(artifact_store, "root", lambda: tmp_path / "artifacts")
    artifact = artifact_store.store_bytes(RUN_ID, "report.md", b"saved")
    url = f"/api/v1/runs/{RUN_ID}/artifacts/{artifact['filename']}/review"
    assert (await client.get(url)).json() == {"status": "none"}
    artifact_store.write_review(artifact, {"status": "no_objection", "issues": []})
    body = (await client.get(url)).json()
    assert body["status"] == "no_objection" and body["artifact_sha256"] == artifact["sha256"]
    assert (await client.get(f"/api/v1/runs/{RUN_ID}/artifacts/..%2Fx/review")).status_code in (400, 404)
    # The note is not reachable as a downloadable artifact.
    assert (await client.get(f"/api/v1/runs/{RUN_ID}/artifacts/_reviews")).status_code == 400
