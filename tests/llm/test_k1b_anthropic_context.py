"""K1b (docs/plans/0162/K1-native-tool-protocol.md point 12): on Claude's native path nothing
already sent is edited. Old tool results are cleared by the API (context editing), not trimmed
here; a screenshot stays byte for byte; an endpoint that refuses context editing falls back to
local trimming, and the run record says so. Other providers trim locally as before.
Claude responses follow the documented Messages API shapes (no network, no key).
"""
import json

import httpx
import pytest

from arslan import execution_budget
from arslan.llm import param_heal
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.openai_provider import OpenAIProvider
from arslan.runtime_policy import bounded_history
from server.orchestrator import tool_loop
from server.registry import executors

CONTEXT_BETA = "context-management-2025-06-27"
# E22's values as the user set them after K3's Claude run (K3b, 2026-10-20): 100k / 40k, keep 6. A first
# clearing rewrites everything after the system prompt once, so clear only in long tasks and a lot at once.
CLEAR = {"type": "clear_tool_uses_20250919",
         "trigger": {"type": "input_tokens", "value": 100_000},
         "keep": {"type": "tool_uses", "value": 6},
         "clear_at_least": {"type": "input_tokens", "value": 40_000}}


def tool_reply(call_id, query, sig):
    return {"role": "assistant", "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [{"type": "thinking", "thinking": "", "signature": sig},
                        {"type": "tool_use", "id": call_id, "name": "web_search", "input": {"query": query}}]}


END = {"role": "assistant", "stop_reason": "end_turn", "usage": {"input_tokens": 20, "output_tokens": 3},
       "content": [{"type": "text", "text": "Done."}]}
THREE_STEPS = [tool_reply("toolu_01", "one", "s1"), tool_reply("toolu_02", "two", "s2"),
               tool_reply("toolu_03", "three", "s3"), END]


def refusal(message: str, status: int = 400) -> httpx.Response:
    return httpx.Response(status, json={"type": "error", "error": {"type": "invalid_request_error",
                                                                   "message": message}})


class Search:
    """A result big enough that a 1,500-character history bound must evict the oldest batch."""

    def __init__(self, images=False):
        self.images = images

    async def execute(self, args):
        result = {"ok": True, "external": False, "summary": f"result-{args['query']} " + "x" * 900}
        if self.images:
            result.update(images=[{"mime_type": "image/png", "data": f"PNG-{args['query']}"}], image_label="Notes")
        return result


async def _resolve():
    return [{"key": "web_search", "description": "Search the web"}]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    param_heal.forget()
    yield
    param_heal.forget()


@pytest.fixture
def tight_history(monkeypatch):
    """Every local trim runs with a 1,500-character bound, so any path that trims shows it."""
    def tight(messages, max_chars=0, **kwargs):
        return bounded_history(messages, max_chars=1_500, **kwargs)
    monkeypatch.setattr(tool_loop, "bounded_history", tight)


async def claude_turn(monkeypatch, replies, *, model="claude-opus-5-5", search=None, base_url=""):
    sent, headers = [], []

    def handler(request):
        sent.append(json.loads(request.content))
        headers.append(dict(request.headers))
        reply = replies[len(sent) - 1]
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)
    adapter = LLMAdapter("anthropic", model)
    adapter._provider = AnthropicProvider(model, api_key="k", base_url=base_url,
                                          transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setitem(executors.EXECUTORS, "web_search", search or Search())
    result = await tool_loop.run_native(system="S", user_content="Find three sources", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=_resolve)
    return result, sent, headers


def unmarked(messages):
    """K3 moves the tail cache breakpoint every step; the content sent stays the same."""
    from tests.llm.test_k3_cache_breakpoints import unmarked as strip
    return strip(messages)


def results_text(request):
    return json.dumps(request["messages"])


# ── Claude goes native by default ─────────────────────────────────────────────────────

async def test_claude_gets_the_native_protocol_by_default(monkeypatch):
    result, sent, _ = await claude_turn(monkeypatch, [tool_reply("toolu_01", "one", "s1"), END])
    assert result["final"] == "Done."
    assert any(b.get("type") == "tool_result" for b in sent[1]["messages"][2]["content"])
    assert "TOOL RESULT for" not in results_text(sent[1])


# ── nothing sent is edited later ──────────────────────────────────────────────────────

async def test_a_sent_screenshot_stays_byte_for_byte(monkeypatch):
    _, sent, _ = await claude_turn(monkeypatch, THREE_STEPS, search=Search(images=True))
    assert unmarked(sent[3]["messages"][:3]) == unmarked(sent[1]["messages"][:3])
    assert "PNG-one" in results_text(sent[3]) and "no longer shown" not in results_text(sent[3])


async def test_claude_native_history_is_not_trimmed_locally(monkeypatch, tight_history):
    _, sent, _ = await claude_turn(monkeypatch, THREE_STEPS)
    assert unmarked(sent[3]["messages"][:3]) == unmarked(sent[1]["messages"][:3])
    assert "result-one" in results_text(sent[3])


async def test_requests_ask_the_api_to_clear_old_tool_uses(monkeypatch):
    _, sent, headers = await claude_turn(monkeypatch, THREE_STEPS)
    for body, head in zip(sent, headers):
        assert body["context_management"] == {"edits": [CLEAR]}
        assert CONTEXT_BETA in head["anthropic-beta"].split(",")


def test_only_tools_in_the_request_are_excluded_from_clearing():
    provider = AnthropicProvider("claude-opus-5-5", api_key="k")
    tools = [{"type": "function", "function": {"name": n, "description": n, "parameters": {"type": "object"}}}
             for n in ("web_search", "read_skill", "update_plan")]
    messages = provider.build_trajectory_messages("S", [{"role": "user", "content": "hi"}])
    edit = provider._payload(messages, 0.7, tools)["context_management"]["edits"][0]
    assert edit["exclude_tools"] == ["update_plan", "read_skill"]


async def test_cleared_tool_uses_are_counted_in_the_run_record(monkeypatch):
    end = dict(END, context_management={"applied_edits": [
        {"type": "clear_tool_uses_20250919", "cleared_tool_uses": 8, "cleared_input_tokens": 50_000}]})
    with execution_budget.scope() as budget:
        await claude_turn(monkeypatch, [tool_reply("toolu_01", "one", "s1"), end])
    assert budget.snapshot()["context_events"] == [
        {"kind": "tool_uses_cleared", "reason": "clear_tool_uses_20250919", "count": 8, "request": 2},
        {"kind": "input_tokens_cleared", "reason": "clear_tool_uses_20250919", "count": 50_000, "request": 2}]


# ── other providers trim locally, as before ───────────────────────────────────────────

def _openai(call_id, query):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": "web_search", "arguments": json.dumps({"query": query})}}]},
        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


async def test_other_providers_still_trim_locally(monkeypatch, tight_history):
    sent = []
    replies = [_openai("c1", "one"), _openai("c2", "two"), _openai("c3", "three"),
               {"choices": [{"message": {"role": "assistant", "content": "Done."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}]

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(sent) - 1])
    adapter = LLMAdapter("openai", "gpt-x", api_key="k", base_url="https://llm.example/v1")
    adapter._provider = OpenAIProvider(model="gpt-x", api_key="k", base_url="https://llm.example/v1",
                                       transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setitem(executors.EXECUTORS, "web_search", Search())
    await tool_loop.run_native(system="S", user_content="Find three sources", history=[],
                               emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=_resolve)
    assert "result-one" in json.dumps(sent[1]["messages"])
    assert "result-one" not in json.dumps(sent[3]["messages"])
    assert "context_management" not in sent[3]


# ── refused clearing: resent without it, local trimming, marked ───────────────────────

async def test_refused_clearing_falls_back_to_local_trimming_and_is_marked(monkeypatch, tight_history):
    replies = [refusal("context_management: Extra inputs are not permitted"), *THREE_STEPS]
    with execution_budget.scope() as budget:
        result, sent, headers = await claude_turn(monkeypatch, replies)
    assert result["final"] == "Done."
    assert "context_management" not in sent[1] and CONTEXT_BETA not in headers[1].get("anthropic-beta", "")
    assert all("context_management" not in body for body in sent[2:])
    assert "result-one" not in results_text(sent[4])                 # trimmed here again
    events = budget.snapshot()["context_events"]
    assert [e["kind"] for e in events if e["kind"] == "server_clearing_off"] == ["server_clearing_off"]


async def test_a_refused_context_beta_is_dropped_with_its_field(monkeypatch):
    replies = [refusal(f"Unexpected value(s) `{CONTEXT_BETA}` for the `anthropic-beta` header."), END]
    _, sent, headers = await claude_turn(monkeypatch, replies)
    assert "context_management" not in sent[1]
    assert CONTEXT_BETA not in headers[1].get("anthropic-beta", "")
    assert "thinking-binding-controls-2026-08-01" in headers[1]["anthropic-beta"]


# ── a context-overflow compaction is the one allowed edit, and it is marked ───────────

async def test_a_context_overflow_compaction_is_marked(monkeypatch):
    replies = [tool_reply("toolu_01", "one", "s1"), tool_reply("toolu_02", "two", "s2"),
               refusal("prompt is too long: 1200000 tokens > 1000000 maximum"), END]
    with execution_budget.scope() as budget:
        result, _, _ = await claude_turn(monkeypatch, replies)
    assert result["final"] == "Done."
    assert any(e["kind"] == "compacted" and e["reason"] == "context_overflow"
               for e in budget.snapshot()["context_events"])


# ── review fixes (#213) ──────────────────────────────────────────────────────────────

async def test_a_third_party_anthropic_endpoint_keeps_local_trimming(monkeypatch, tight_history):
    # A compatible host may ignore context_management silently: no server clearing would mean no
    # trimming at all. Only Claude on Anthropic's own host gets it; everything else trims here.
    _, sent, headers = await claude_turn(monkeypatch, THREE_STEPS, search=Search(images=True),
                                         base_url="https://api.example-llm.test/anthropic")
    assert all("context_management" not in body for body in sent)
    assert all(CONTEXT_BETA not in head.get("anthropic-beta", "") for head in headers)
    assert "result-one" not in results_text(sent[3])                      # trimmed locally


async def test_a_non_claude_model_on_anthropics_host_gets_no_server_clearing(monkeypatch):
    _, sent, _ = await claude_turn(monkeypatch, [tool_reply("toolu_01", "one", "s1"), END], model="other-model")
    assert all("context_management" not in body for body in sent)


def _assistant_after(request):
    return [m for m in request["messages"] if m["role"] == "assistant"][-1]


async def test_replaced_tool_call_text_is_not_replayed(monkeypatch):
    # The host replaces tool-call text with a notice; replaying the original blocks verbatim would
    # put the malformed call back in front of the model as an example to imitate.
    leak = {"role": "assistant", "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "thinking", "thinking": "", "signature": "s1"},
                        {"type": "text", "text": '<tool_call>{"name": "web_search"}</tool_call>'}]}
    _, sent, _ = await claude_turn(monkeypatch, [leak, END])
    replayed = json.dumps(_assistant_after(sent[1]))
    assert "Non-executable tool-call text omitted." in replayed
    assert "<tool_call>" not in replayed and '"thinking"' not in replayed


async def test_a_stripped_status_echo_is_not_replayed(monkeypatch):
    echo = {"role": "assistant", "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "thinking", "thinking": "", "signature": "s1"},
                        {"type": "text", "text": '<agent_status note="x">Work so far: 1 tool call.</agent_status>'
                                                 "I'll search for that now."}]}
    _, sent, _ = await claude_turn(monkeypatch, [echo, END])
    replayed = json.dumps(_assistant_after(sent[1]))
    assert "I'll search for that now." in replayed
    assert "agent_status" not in replayed and '"thinking"' not in replayed


# ── a metering proxy that forwards verbatim to api.anthropic.com (bench, M1) ─────────

from arslan.llm.providers import anthropic_provider  # noqa: E402

PROXY = "http://127.0.0.1:8901/c/arslan-T1-r1"


def test_the_first_party_hosts_come_from_the_environment_only():
    assert anthropic_provider._first_party_hosts({}) == frozenset()
    assert anthropic_provider._first_party_hosts(
        {"ARSLAN_ANTHROPIC_FIRST_PARTY_HOSTS": " 127.0.0.1:8901, Proxy.Local:9000 ,"}) == {
        "127.0.0.1:8901", "proxy.local:9000"}


async def test_a_listed_metering_proxy_is_treated_as_anthropics_host(monkeypatch, tight_history):
    monkeypatch.setattr(anthropic_provider, "_FIRST_PARTY_HOSTS", frozenset({"127.0.0.1:8901"}))
    _, sent, headers = await claude_turn(monkeypatch, THREE_STEPS, base_url=PROXY)
    assert all(body["context_management"] == {"edits": [CLEAR]} for body in sent)
    assert CONTEXT_BETA in headers[0]["anthropic-beta"]
    assert unmarked(sent[3]["messages"][:3]) == unmarked(sent[1]["messages"][:3])            # nothing trimmed here


@pytest.mark.parametrize("listed", [frozenset(), frozenset({"127.0.0.1:8902"}), frozenset({"127.0.0.1"})])
async def test_an_unlisted_proxy_still_trims_locally(monkeypatch, tight_history, listed):
    monkeypatch.setattr(anthropic_provider, "_FIRST_PARTY_HOSTS", listed)
    _, sent, _ = await claude_turn(monkeypatch, THREE_STEPS, base_url=PROXY)
    assert all("context_management" not in body for body in sent)
    assert "result-one" not in results_text(sent[3])


async def test_a_listed_proxy_still_needs_a_claude_model(monkeypatch):
    monkeypatch.setattr(anthropic_provider, "_FIRST_PARTY_HOSTS", frozenset({"127.0.0.1:8901"}))
    _, sent, _ = await claude_turn(monkeypatch, [tool_reply("toolu_01", "one", "s1"), END],
                                   model="other-model", base_url=PROXY)
    assert all("context_management" not in body for body in sent)
