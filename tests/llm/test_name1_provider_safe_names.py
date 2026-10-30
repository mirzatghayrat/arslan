"""NAME1 (v0.1.64): every provider gets each tool under a name its function-name rule takes.

MCP lets a tool's name hold dots, and some servers send spaces or worse. An MCP tool's key keeps the
server's name (`mcp_7__read.file-v2`, server/mcp/discovery.py). One name outside a provider's rule
refuses the whole request, and F3 used to read that refusal as a schema refusal: it left a working tool
out and told the model the tool's schema was refused (docs/plans/0164/README.md, NAME1).

Each provider's rule as its own reference states it (read 2026-10-30), written as a pattern in RULES:
- OpenAI (openai-python, FunctionDefinition.name): letters, digits, `_` and `-`; at most 64.
- DeepSeek (api-docs.deepseek.com, create chat completion): the same characters; at most 128.
- Anthropic (platform.claude.com, Define tools): `^[a-zA-Z0-9_-]{1,128}$`.
- Gemini (google-genai, FunctionDeclaration.name): `.` and `:` too, a letter or `_` first; at most 128.
Not checked live: whether a provider also checks the names of earlier calls in its history. NAME1
renames those too, so the answer doesn't change what is sent.

The fake models here call a tool by the name the request gave it, as a real model does. This file
doesn't import arslan/llm/tool_names.py: it reads every name off the payloads.
"""
import json
import re

import httpx
import pytest

from arslan.llm import param_heal, trajectory
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from arslan.llm.providers.openai_provider import OpenAIProvider
from server.orchestrator import tool_loop
from server.registry import executors

RULES = {
    "openai": re.compile(r"[A-Za-z0-9_-]{1,64}"),
    "deepseek": re.compile(r"[A-Za-z0-9_-]{1,128}"),
    "anthropic": re.compile(r"[a-zA-Z0-9_-]{1,128}"),
    "gemini": re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,127}"),
}
DOTTED = "mcp_7__read.file-v2"      # MCP's own rule takes it; OpenAI, DeepSeek and Anthropic don't
SPACED = "mcp_7__read file"         # outside MCP's rule too; Gemini doesn't take it either
READ = "Read a file"
SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}


@pytest.fixture(autouse=True)
def native(monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    param_heal.forget()
    tool_loop._BAD_TOOLS.clear()
    yield
    param_heal.forget()
    tool_loop._BAD_TOOLS.clear()


@pytest.fixture(autouse=True)
def quiet_mcp(monkeypatch):
    from server.mcp import executor
    from server.services import recap_service

    async def quiet(*a, **k):
        return None
    monkeypatch.setattr(executor, "not_ready_for_key", quiet)
    monkeypatch.setattr(recap_service, "log_event", quiet)


class Reader:
    def __init__(self):
        self.calls = []

    async def execute(self, args):
        self.calls.append(args)
        return {"ok": True, "external": False, "summary": f"read {args.get('path')}"}


def resolver(*keys):
    async def resolve():
        return [{"key": "web_search", "description": "Search the web"},
                *({"key": key, "description": READ, "input_schema": SCHEMA} for key in keys)]
    return resolve


async def run(monkeypatch, adapter, key, reader=None, **kwargs):
    reader = reader or Reader()
    monkeypatch.setitem(executors.EXECUTORS, key, reader)
    result = await tool_loop.run_native(system="S", user_content="Read a.txt", history=[], emit=lambda e: None,
                                        on_chunk=lambda c: None, resolve_tools=kwargs.pop("resolve", resolver(key)),
                                        adapter_override=adapter, conversation_id="c1", **kwargs)
    return result, reader


# ── OpenAI-compatible (DeepSeek's shape) ─────────────────────────────────────────────

OPENAI_END = {"choices": [{"message": {"role": "assistant", "content": "Done."}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def openai_call(name, path="a.txt"):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": name, "arguments": json.dumps({"path": path})}}]},
        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def openai_names(body):
    return ([t["function"]["name"] for t in body.get("tools") or []]
            + [c["function"]["name"] for m in body["messages"] for c in m.get("tool_calls") or []])


def sent_name(body, description=READ):
    return next(t["function"]["name"] for t in body["tools"] if t["function"]["description"] == description)


def deepseek(handler):
    adapter = LLMAdapter("openai", "deepseek-chat", api_key="k", base_url="https://llm.example/v1")
    adapter._provider = OpenAIProvider(model="deepseek-chat", api_key="k", base_url="https://llm.example/v1",
                                       transport=httpx.MockTransport(handler))
    return adapter


def calls_back(sent):
    """A model that calls the read tool by the name it was given, then answers."""
    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, json=openai_call(sent_name(body)) if len(sent) == 1 else OPENAI_END)
    return handler


async def test_deepseek_gets_names_it_takes_and_the_call_runs_the_real_tool(monkeypatch):
    sent = []
    result, reader = await run(monkeypatch, deepseek(calls_back(sent)), DOTTED)
    assert result["final"] == "Done." and reader.calls == [{"path": "a.txt"}]
    for body in sent:
        assert all(RULES["openai"].fullmatch(n) and RULES["deepseek"].fullmatch(n) for n in openai_names(body))
    name = sent_name(sent[0])
    assert name != DOTTED and sent_name(sent[1]) == name                    # the same name every request
    earlier = [c["function"]["name"] for m in sent[1]["messages"] for c in m.get("tool_calls") or []]
    assert earlier == [name]                                                # the earlier call, as the model made it
    assert "web_search" in openai_names(sent[0])                            # a name it takes stays as it is


async def test_the_legacy_rendering_sends_the_same_names(monkeypatch):
    monkeypatch.setenv("ARSLAN_TOOL_PROTOCOL", "legacy")
    sent = []
    result, reader = await run(monkeypatch, deepseek(calls_back(sent)), DOTTED)
    assert result["final"] == "Done." and reader.calls == [{"path": "a.txt"}]
    assert "TOOL RESULT for" in json.dumps(sent[1]["messages"])
    assert all(RULES["openai"].fullmatch(n) for body in sent for n in openai_names(body))


async def test_a_schema_refusal_by_the_name_sent_still_leaves_out_only_that_tool(monkeypatch):
    # F3 reads a refusal against the names the request carried (OpenAI: "Invalid schema for function 'x'").
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) == 1:
            return httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": (
                f"Invalid schema for function '{sent_name(body)}': 'pattern' is not permitted")}})
        return httpx.Response(200, json=OPENAI_END)

    async def resolve():
        return [*(await resolver(DOTTED)()),
                {"key": "mcp_7__list_files", "description": "List files", "input_schema": SCHEMA}]
    result, _ = await run(monkeypatch, deepseek(handler), DOTTED, resolve=resolve)
    assert result["final"] == "Done." and len(sent) == 2
    refused = sent_name(sent[0])
    kept = [t["function"]["name"] for t in sent[1]["tools"]]
    assert refused not in kept and {"web_search", "mcp_7__list_files"} <= set(kept)
    notes = [m["content"] for m in sent[1]["messages"] if "is not available in this turn" in str(m.get("content"))]
    assert notes and f"the MCP tool {refused} is not available" in str(notes[-1])   # as the model knows it


async def test_an_unknown_call_is_told_the_names_it_can_call(monkeypatch):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, json=openai_call("mcp_7__read_file") if len(sent) == 1 else OPENAI_END)
    await run(monkeypatch, deepseek(handler), DOTTED)
    answer = next(m["content"] for m in sent[1]["messages"] if m.get("role") == "tool")
    listed = re.search(r"available tools include: ([^;]+);", answer).group(1).split(", ")
    assert sent_name(sent[0]) in listed and set(listed) <= set(openai_names(sent[0]))


@pytest.mark.parametrize("mangle", [str.upper, lambda name: name[:-1] + ("0" if name[-1] != "0" else "1"),
                                    lambda name: name[:-10]], ids=["case-folded", "one character off", "no hash"])
async def test_a_name_that_only_looks_like_a_tool_runs_nothing(monkeypatch, mangle):
    """The way back is an exact lookup: a name close to one the request gave runs no tool."""
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, json=openai_call(mangle(sent_name(body))) if len(sent) == 1 else OPENAI_END)
    _, reader = await run(monkeypatch, deepseek(handler), DOTTED)
    answer = next(m["content"] for m in sent[1]["messages"] if m.get("role") == "tool")
    assert reader.calls == [] and "is not available to you" in answer


# ── Claude ───────────────────────────────────────────────────────────────────────────

CLAUDE_END = {"role": "assistant", "stop_reason": "end_turn", "usage": {"input_tokens": 2, "output_tokens": 1},
              "content": [{"type": "text", "text": "Done."}]}


def claude_names(body):
    return ([t["name"] for t in body.get("tools") or []]
            + [b["name"] for m in body["messages"] if isinstance(m["content"], list)
               for b in m["content"] if b.get("type") == "tool_use"])


async def test_claude_gets_names_it_takes_and_its_blocks_come_back_unchanged(monkeypatch):
    sent, replies = [], []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) > 1:
            return httpx.Response(200, json=CLAUDE_END)
        name = next(t["name"] for t in body["tools"] if t.get("description") == READ)
        replies.append({"role": "assistant", "stop_reason": "tool_use",
                        "usage": {"input_tokens": 2, "output_tokens": 1},
                        "content": [{"type": "thinking", "thinking": "", "signature": "sig-1"},
                                    {"type": "tool_use", "id": "toolu_01", "name": name, "input": {"path": "a.txt"}}]})
        return httpx.Response(200, json=replies[0])
    adapter = LLMAdapter("anthropic", "claude-opus-5-5")
    adapter._provider = AnthropicProvider("claude-opus-5-5", api_key="k", transport=httpx.MockTransport(handler))
    result, reader = await run(monkeypatch, adapter, DOTTED)
    assert result["final"] == "Done." and reader.calls == [{"path": "a.txt"}]
    assert all(RULES["anthropic"].fullmatch(n) for body in sent for n in claude_names(body))
    assert json.dumps(sent[1]["messages"][1]["content"]) == json.dumps(replies[0]["content"])   # append-only


# ── Gemini ───────────────────────────────────────────────────────────────────────────

GEMINI_END = {"candidates": [{"content": {"parts": [{"text": "Done."}]}}]}


def gemini_names(body):
    parts = [p for c in body["contents"] for p in c.get("parts") or []]
    return ([d["name"] for t in body.get("tools") or [] for d in t.get("functionDeclarations") or []]
            + [p["functionCall"]["name"] for p in parts if "functionCall" in p]
            + [p["functionResponse"]["name"] for p in parts if "functionResponse" in p])


async def test_gemini_gets_names_it_takes_and_answers_each_call_by_its_name(monkeypatch):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) > 1:
            return httpx.Response(200, json=GEMINI_END)
        name = next(d["name"] for d in body["tools"][0]["functionDeclarations"] if d["description"] == READ)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"functionCall": {"name": name, "args": {"path": "a.txt"}, "id": "fc1"}, "thoughtSignature": "ts"}]}}]})
    adapter = LLMAdapter("gemini", "gemini-x")
    adapter._provider = GeminiProvider("gemini-x", api_key="k", transport=httpx.MockTransport(handler))
    result, reader = await run(monkeypatch, adapter, SPACED)
    assert result["final"] == "Done." and reader.calls == [{"path": "a.txt"}]
    assert all(RULES["gemini"].fullmatch(n) for body in sent for n in gemini_names(body))
    parts = [p for c in sent[1]["contents"] for p in c.get("parts") or []]
    called = [p["functionCall"]["name"] for p in parts if "functionCall" in p]
    answered = [p["functionResponse"]["name"] for p in parts if "functionResponse" in p]
    assert called == answered and len(called) == 1                          # the response answers its call by name


async def test_gemini_answers_a_call_by_the_name_the_model_wrote(monkeypatch):
    """K7's find_tools shows real keys, and a direct call by one runs: its response carries that name too."""
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) > 1:
            return httpx.Response(200, json=GEMINI_END)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"functionCall": {"name": DOTTED, "args": {"path": "a.txt"}, "id": "fc1"}, "thoughtSignature": "ts"}]}}]})
    adapter = LLMAdapter("gemini", "gemini-x")
    adapter._provider = GeminiProvider("gemini-x", api_key="k", transport=httpx.MockTransport(handler))
    result, reader = await run(monkeypatch, adapter, DOTTED)
    assert result["final"] == "Done." and reader.calls == [{"path": "a.txt"}]
    parts = [p for c in sent[1]["contents"] for p in c.get("parts") or []]
    called = [p["functionCall"]["name"] for p in parts if "functionCall" in p]
    answered = [p["functionResponse"]["name"] for p in parts if "functionResponse" in p]
    assert called == answered == [DOTTED]


async def test_the_legacy_rendering_answers_gemini_by_the_same_name(monkeypatch):
    """The legacy rendering replays Gemini's parts and its own function response (trajectory.to_legacy)."""
    monkeypatch.setenv("ARSLAN_TOOL_PROTOCOL", "legacy")
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if len(sent) > 1:
            return httpx.Response(200, json=GEMINI_END)
        name = next(d["name"] for d in body["tools"][0]["functionDeclarations"] if d["description"] == READ)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"functionCall": {"name": name, "args": {"path": "a.txt"}, "id": "fc1"}}]}}]})
    adapter = LLMAdapter("gemini", "gemini-x")
    adapter._provider = GeminiProvider("gemini-x", api_key="k", transport=httpx.MockTransport(handler))
    result, reader = await run(monkeypatch, adapter, SPACED)
    assert result["final"] == "Done." and reader.calls == [{"path": "a.txt"}]
    assert all(RULES["gemini"].fullmatch(n) for body in sent for n in gemini_names(body))
    parts = [p for c in sent[1]["contents"] for p in c.get("parts") or []]
    called = [p["functionCall"]["name"] for p in parts if "functionCall" in p]
    answered = [p["functionResponse"]["name"] for p in parts if "functionResponse" in p]
    assert called == answered and len(called) == 1


# ── an earlier call made under the key itself (another provider, an older Arslan) ─────

def earlier_call(key):
    call = {"id": "c1", "name": key, "arguments": {"path": "a"}, "arguments_raw": '{"path": "a"}'}
    return [trajectory.request("Read a"), trajectory.assistant(None, [call]), trajectory.tool_result("c1", key, "text")]


def wired(key):
    return tool_loop._native_tool_schemas([{"key": key, "description": READ, "input_schema": SCHEMA}],
                                          allow_escalation=False)


def capturing(sent, reply):
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=reply)
    return httpx.MockTransport(handler)


async def test_each_provider_gets_an_earlier_call_under_a_name_it_takes():
    sent = []
    openai = LLMAdapter("openai", "deepseek-chat", api_key="k", base_url="https://llm.example/v1")
    openai._provider = OpenAIProvider(model="deepseek-chat", api_key="k", base_url="https://llm.example/v1",
                                      transport=capturing(sent, OPENAI_END))
    await openai.chat_trajectory("S", earlier_call(DOTTED), tools=wired(DOTTED))
    assert len(openai_names(sent[-1])) == 2 and all(RULES["openai"].fullmatch(n) for n in openai_names(sent[-1]))

    claude = LLMAdapter("anthropic", "claude-sonnet-5")
    claude._provider = AnthropicProvider("claude-sonnet-5", api_key="k", transport=capturing(sent, CLAUDE_END))
    await claude.chat_trajectory("S", earlier_call(DOTTED), tools=wired(DOTTED))
    assert len(claude_names(sent[-1])) == 2 and all(RULES["anthropic"].fullmatch(n) for n in claude_names(sent[-1]))

    gemini = LLMAdapter("gemini", "gemini-x")
    gemini._provider = GeminiProvider("gemini-x", api_key="k", transport=capturing(sent, GEMINI_END))
    await gemini.chat_trajectory("S", earlier_call(SPACED), tools=wired(SPACED))
    assert len(gemini_names(sent[-1])) == 2 and all(RULES["gemini"].fullmatch(n) for n in gemini_names(sent[-1]))


async def test_the_trajectory_keeps_the_real_keys():
    sent, messages = [], earlier_call(DOTTED)
    before = json.dumps(messages)
    adapter = LLMAdapter("openai", "deepseek-chat", api_key="k", base_url="https://llm.example/v1")
    adapter._provider = OpenAIProvider(model="deepseek-chat", api_key="k", base_url="https://llm.example/v1",
                                       transport=capturing(sent, openai_call("x")))
    tools = wired(DOTTED)
    reply = await adapter.chat_trajectory("S", messages, tools=tools)
    assert json.dumps(messages) == before and tools[0]["function"]["name"] == DOTTED   # nothing edited in place
    assert reply.tool_calls[0]["function"]["name"] == "x"                  # not a tool it was given: unchanged
