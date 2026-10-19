"""K1a (docs/plans/0162/K1-native-tool-protocol.md): Claude and Gemini get their own native tool protocol.

The model sees which tool it called, with which arguments, and what came back; Claude's
thinking blocks go back byte for byte; the step's status is its own block, kept in place.
Claude responses here follow the documented Messages API shapes (no network, no key).
"""
import json

import httpx
import pytest

from arslan import execution_budget
from arslan.llm import param_heal, trajectory
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers import anthropic_provider
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from server.orchestrator import model_call as mc
from server.orchestrator import tool_loop
from server.registry import executors

BINDING_BETA = "thinking-binding-controls-2026-08-01"
TOOLS = [{"type": "function", "function": {
    "name": "web_search", "description": "Search the web.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}]


def tool_reply(*calls, thinking="sig-1", text="Working.", extra=None):
    content = []
    if thinking:
        content.append({"type": "thinking", "thinking": "", "signature": thinking})
    content.extend(extra or [])
    if text:
        content.append({"type": "text", "text": text})
    for call_id, query in calls:
        content.append({"type": "tool_use", "id": call_id, "name": "web_search", "input": {"query": query}})
    return {"role": "assistant", "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": content}


END = {"role": "assistant", "stop_reason": "end_turn", "usage": {"input_tokens": 20, "output_tokens": 3},
       "content": [{"type": "text", "text": "Done."}]}


def refusal(message: str) -> httpx.Response:
    return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": message}})


class Search:
    def __init__(self, images=False, external=True):
        self.images, self.external = images, external

    async def execute(self, args):
        result = {"ok": True, "external": self.external, "summary": f"result-{args['query']}"}
        if self.images:
            result.update(images=[{"mime_type": "image/png", "data": "AAAA"}], image_label="Notes")
        return result


async def _resolve():
    return [{"key": "web_search", "description": "Search the web"}]


@pytest.fixture(autouse=True)
def native(monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    monkeypatch.setattr(anthropic_provider, "NATIVE_TRAJECTORY", True, raising=False)
    param_heal.forget()
    yield
    param_heal.forget()


async def claude_turn(monkeypatch, replies, *, model="claude-sonnet-5", key="k", search=None, history=None):
    sent, headers = [], []

    def handler(request):
        sent.append(json.loads(request.content))
        headers.append(dict(request.headers))
        reply = replies[len(sent) - 1]
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)
    adapter = LLMAdapter("anthropic", model)
    adapter._provider = AnthropicProvider(model, api_key=key, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setitem(executors.EXECUTORS, "web_search", search or Search())
    result = await tool_loop.run_native(system="S", user_content="Find two sources", history=history or [],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=_resolve)
    return result, sent, headers


def results_of(message):
    return [b for b in message["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]


# ── Claude: its own calls, arguments and results, paired ─────────────────────────────

async def test_claude_sees_its_calls_and_their_results_paired(monkeypatch):
    first = tool_reply(("toolu_01", "one"), ("toolu_02", "two"))
    result, sent, _ = await claude_turn(monkeypatch, [first, END])
    assert result["final"] == "Done."
    messages = sent[1]["messages"]
    assert messages[0] == {"role": "user", "content": "Find two sources"}
    assert messages[1]["role"] == "assistant"
    assert [b["id"] for b in messages[1]["content"] if b["type"] == "tool_use"] == ["toolu_01", "toolu_02"]
    batch = messages[2]
    assert [r["tool_use_id"] for r in results_of(batch)] == ["toolu_01", "toolu_02"]
    assert batch["content"][:2] == results_of(batch)                  # results lead the user message
    assert "result-one" in json.dumps(results_of(batch)[0]["content"])
    assert "Native tool invocation completed" not in json.dumps(sent[1])


async def test_thinking_blocks_go_back_byte_for_byte(monkeypatch):
    first = tool_reply(("toolu_01", "one"), extra=[{"type": "redacted_thinking", "data": "enc-blob"}])
    _, sent, _ = await claude_turn(monkeypatch, [first, END])
    assert json.dumps(sent[1]["messages"][1]["content"]) == json.dumps(first["content"])


async def test_a_batch_with_screenshots_stays_paired(monkeypatch):
    first = tool_reply(("toolu_01", "one"), ("toolu_02", "two"))
    _, sent, _ = await claude_turn(monkeypatch, [first, END], search=Search(images=True, external=False))
    results = results_of(sent[1]["messages"][2])
    assert [r["tool_use_id"] for r in results] == ["toolu_01", "toolu_02"]
    images = [b for r in results for b in r["content"] if isinstance(b, dict) and b.get("type") == "image"]
    assert images == [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}] * 2


# ── the status block: its own block, after the results, never edited later ──────────

async def test_the_status_is_its_own_block_and_stays_where_it_was(monkeypatch):
    replies = [tool_reply(("toolu_a", "one")), tool_reply(("toolu_b", "two"), thinking="sig-2"), END]
    _, sent, _ = await claude_turn(monkeypatch, replies)
    step1 = sent[1]["messages"][2]["content"]
    assert step1[0]["type"] == "tool_result" and "<agent_status" not in json.dumps(step1[0])
    assert step1[-1]["type"] == "text" and step1[-1]["text"].startswith("<agent_status")
    later = sent[2]["messages"]
    assert later[:3] == sent[1]["messages"][:3]                         # nothing sent is edited
    assert json.dumps(later[3]["content"]) == json.dumps(replies[1]["content"])
    step2 = later[4]["content"]
    assert results_of(later[4])[0]["tool_use_id"] == "toolu_b"
    assert step2[-1]["type"] == "text" and step2[-1]["text"].startswith("<agent_status")


# ── forced wrap-up: tool_choice none instead of a TypeError ─────────────────────────

def _capturing(sent, reply):
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=reply)
    return httpx.MockTransport(handler)


async def test_claude_takes_tool_choice_none():
    sent = []
    provider = AnthropicProvider("claude-sonnet-5", api_key="k", transport=_capturing(sent, END))
    await provider.chat([{"role": "user", "content": "hi"}], tools=TOOLS, tool_choice="none")
    assert sent[0]["tool_choice"] == {"type": "none"} and sent[0]["tools"]


async def test_gemini_takes_tool_choice_none():
    sent = []
    reply = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    provider = GeminiProvider("gemini-x", api_key="k", transport=_capturing(sent, reply))
    await provider.chat([{"role": "user", "content": "hi"}], tools=TOOLS, tool_choice="none")
    assert sent[0]["toolConfig"] == {"functionCallingConfig": {"mode": "NONE"}}


# ── preserved thinking: drop_block on the models that check, never with between_tools ─

@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"])
async def test_native_requests_ask_to_drop_invalidated_blocks(monkeypatch, model):
    _, sent, headers = await claude_turn(monkeypatch, [tool_reply(("toolu_01", "one")), END], model=model)
    for payload, head in zip(sent, headers):
        assert payload["thinking"] == {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
        assert BINDING_BETA in head.get("anthropic-beta", "")


async def test_earlier_models_get_no_binding_field(monkeypatch):
    _, sent, headers = await claude_turn(monkeypatch, [tool_reply(("toolu_01", "one")), END], model="claude-sonnet-5")
    assert "thinking" not in sent[0] and "anthropic-beta" not in headers[0]


async def test_a_refused_binding_field_is_dropped_and_remembered(monkeypatch):
    replies = [refusal("thinking.block_binding: Extra inputs are not permitted"), tool_reply(("toolu_01", "one")), END]
    result, sent, headers = await claude_turn(monkeypatch, replies, model="claude-opus-5-5")
    assert result["final"] == "Done."
    assert "block_binding" not in json.dumps(sent[1]) and BINDING_BETA not in headers[1].get("anthropic-beta", "")
    _, again, again_headers = await claude_turn(monkeypatch, [END], model="claude-opus-5-5")
    assert "block_binding" not in json.dumps(again[0]) and BINDING_BETA not in again_headers[0].get("anthropic-beta", "")


async def test_a_refused_beta_name_drops_its_field_too(monkeypatch):
    message = (f"Unexpected value(s) `{BINDING_BETA}` for the `anthropic-beta` header. "
               "Please consult our documentation at docs.claude.com or try again without the header.")
    result, sent, headers = await claude_turn(monkeypatch, [refusal(message), END], model="claude-opus-5-5")
    assert result["final"] == "Done."
    assert "block_binding" not in json.dumps(sent[1]) and BINDING_BETA not in headers[1].get("anthropic-beta", "")


# ── what is never replayed ──────────────────────────────────────────────────────────

def _one_call_trajectory(provider, reply):
    response = provider._parse_response(reply)
    call = trajectory.call_from_response(response.tool_calls[0], "x")
    return [{"role": "user", "content": "go"},
            trajectory.assistant(response.content, [call], continuation=response.continuation),
            trajectory.tool_result(call["id"], "web_search", "result-one")]


def test_another_key_never_replays_thinking():
    reply = tool_reply(("toolu_01", "one"))
    mine = AnthropicProvider("claude-opus-5-5", api_key="key-a")
    other = AnthropicProvider("claude-opus-5-5", api_key="key-b")
    assert mine.endpoint_fingerprint() != other.endpoint_fingerprint()
    wire_mine = mine.build_trajectory_messages("S", _one_call_trajectory(mine, reply))
    assert json.dumps(wire_mine[2]["content"]) == json.dumps(reply["content"])
    wire_other = other.build_trajectory_messages("S", _one_call_trajectory(mine, reply))
    kinds = [b["type"] for b in wire_other[2]["content"]]
    assert "thinking" not in kinds and "tool_use" in kinds


async def test_the_next_turn_carries_no_earlier_thinking(monkeypatch):
    history = [{"role": "user", "content": "Find two sources"}, {"role": "assistant", "content": "Both done."}]
    _, sent, _ = await claude_turn(monkeypatch, [END], history=history)
    assert '"thinking"' not in json.dumps(sent[0]["messages"])


async def test_a_protocol_refusal_falls_back_to_the_legacy_rendering(monkeypatch):
    bound = ("messages.1.content.0: Invalid `signature` in `thinking` block. "
             "The block is bound to a different conversation.")
    replies = [tool_reply(("toolu_01", "one")), refusal(bound), END]
    result, sent, _ = await claude_turn(monkeypatch, replies)
    assert result["final"] == "Done."
    assert "TOOL RESULT for web_search" in json.dumps(sent[2]["messages"])


def test_anthropic_and_gemini_rejections_read_as_protocol():
    for text in ("messages.2: `tool_use` ids were found without `tool_result` blocks",
                 "Invalid `signature` in `thinking` block",
                 "Please ensure that function response turn comes immediately after a function call turn "
                 "(functionResponse)"):
        request = httpx.Request("POST", "https://x")
        exc = httpx.HTTPStatusError(f"Client error '400 Bad Request'\n{text}", request=request,
                                    response=httpx.Response(400, request=request))
        assert mc.classify(exc) == ("protocol", 400), text


def test_a_schema_refusal_naming_a_thinking_tool_stays_an_input_error():
    # F3 leaves a refused MCP tool out only for "input" errors; the sequential-thinking MCP server's
    # tools carry "thinking" in their names, which must not read as a protocol rejection.
    text = "tools.7.custom.input_schema: JSON schema is invalid (mcp_sequential_thinking_sequentialthinking)"
    request = httpx.Request("POST", "https://x")
    exc = httpx.HTTPStatusError(f"Client error '400 Bad Request'\n{text}", request=request,
                                response=httpx.Response(400, request=request))
    assert mc.classify(exc) == ("input", 400)


# ── the run record notes dropped thinking (counts only) ─────────────────────────────

async def test_dropped_thinking_is_noted_in_the_run_record(monkeypatch):
    first = tool_reply(("toolu_01", "one"))
    later = dict(END, input_transformations=[
        {"type": "thinking_dropped", "path": "messages.1.content.0", "reason": "prefix_binding_mismatch"}])
    with execution_budget.scope() as budget:
        await claude_turn(monkeypatch, [first, later], model="claude-opus-5-5")
    events = budget.snapshot()["context_events"]
    assert events == [{"kind": "thinking_dropped", "reason": "prefix_binding_mismatch", "count": 1, "request": 2}]


# ── Gemini: structured function responses, status kept in place ─────────────────────

GEMINI_CALLS = {"candidates": [{"content": {"parts": [
    {"functionCall": {"name": "web_search", "args": {"query": "one"}, "id": "fc1"}, "thoughtSignature": "ts"}]}}]}
GEMINI_CALLS_2 = {"candidates": [{"content": {"parts": [
    {"functionCall": {"name": "web_search", "args": {"query": "two"}, "id": "fc2"}}]}}]}
GEMINI_END = {"candidates": [{"content": {"parts": [{"text": "Done."}]}}]}


async def gemini_turn(monkeypatch, replies, search):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(sent) - 1])
    adapter = LLMAdapter("gemini", "gemini-x")
    adapter._provider = GeminiProvider("gemini-x", api_key="k", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setitem(executors.EXECUTORS, "web_search", search)
    result = await tool_loop.run_native(system="S", user_content="Find it", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=_resolve)
    return result, sent


async def test_gemini_function_responses_carry_the_result_itself(monkeypatch):
    result, sent = await gemini_turn(monkeypatch, [GEMINI_CALLS, GEMINI_END], Search(external=False))
    assert result["final"] == "Done."
    response = sent[1]["contents"][-1]["parts"][0]["functionResponse"]
    assert response["id"] == "fc1" and response["response"] == {"ok": True, "external": False,
                                                                 "summary": "result-one"}
    assert "TOOL RESULT for" not in json.dumps(sent[1])


async def test_gemini_untrusted_results_stay_framed_as_data(monkeypatch):
    _, sent = await gemini_turn(monkeypatch, [GEMINI_CALLS, GEMINI_END], Search(external=True))
    response = sent[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert set(response) == {"output"} and "EXTERNAL" in response["output"] and "result-one" in response["output"]


async def test_gemini_status_is_its_own_part_and_stays(monkeypatch):
    _, sent = await gemini_turn(monkeypatch, [GEMINI_CALLS, GEMINI_CALLS_2, GEMINI_END], Search(external=False))
    step1 = sent[1]["contents"][-1]["parts"]
    assert "functionResponse" in step1[0] and step1[-1]["text"].startswith("<agent_status")
    assert sent[2]["contents"][:3] == sent[1]["contents"][:3]


# ── review fixes (#212) ──────────────────────────────────────────────────────────────

from arslan.llm.providers.openai_provider import OpenAIProvider  # noqa: E402

OPENAI_END = {"choices": [{"message": {"role": "assistant", "content": "Done."}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


@pytest.mark.parametrize("name", ["mcp_1__get_tool_result", "mcp_1__tool_use_log"])
async def test_a_refused_mcp_tool_named_like_a_protocol_word_is_left_out(monkeypatch, name):
    # F3 on the native path: DeepSeek names the refused function; "tool_result" / "tool_use" in that
    # name read as a protocol word, but it is still one MCP tool's schema: leave it out, carry on.
    from server.mcp import executor
    from server.services import recap_service

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(executor, "not_ready_for_key", quiet)
    monkeypatch.setattr(recap_service, "log_event", quiet)
    tool_loop._BAD_TOOLS.clear()
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if name in [t["function"]["name"] for t in body.get("tools") or []]:
            return httpx.Response(400, json={"error": {"message": (
                f"Invalid schema for function '{name}': 'pattern' is not permitted"), "type": "invalid_request_error"}})
        return httpx.Response(200, json=OPENAI_END)

    async def resolve():
        return [{"key": "web_search", "description": "Search the web"},
                {"key": name, "description": "x", "input_schema": {"type": "object", "properties": {}}}]
    adapter = LLMAdapter("openai", "deepseek-chat", api_key="k", base_url="https://llm.example/v1")
    adapter._provider = OpenAIProvider(model="deepseek-chat", api_key="k", base_url="https://llm.example/v1",
                                       transport=httpx.MockTransport(handler))
    assert adapter.native_trajectory()
    try:
        result = await tool_loop.run_native(system="S", user_content="t", history=[], emit=lambda e: None,
                                            on_chunk=lambda c: None, resolve_tools=resolve,
                                            adapter_override=adapter, conversation_id="c1")
    finally:
        tool_loop._BAD_TOOLS.clear()
    assert result["final"] == "Done." and len(sent) == 2
    assert name not in json.dumps(sent[1]["tools"]) and "web_search" in json.dumps(sent[1]["tools"])


def test_kept_status_blocks_count_toward_the_rendered_size():
    status = "x" * 5_000
    messages = [{"role": "user", "content": "hi"}, trajectory.status(status)]
    assert tool_loop._rendered_size(messages) >= 5_000


def test_the_legacy_rendering_leaves_kept_status_blocks_out():
    calls = [{"id": "c1", "name": "web_search", "arguments": {"query": "one"}, "arguments_raw": '{"query": "one"}'}]
    messages = [{"role": "user", "content": "hi"}, trajectory.assistant(None, calls),
                trajectory.tool_result("c1", "web_search", "result-one"), trajectory.status("<agent_status>old")]
    rendered = json.dumps(trajectory.to_legacy(messages))
    assert "result-one" in rendered and "<agent_status>old" not in rendered
