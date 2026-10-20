"""K3 (docs/plans/0162/K3-prompt-layout-cache.md): where Claude's prompt-cache breakpoints go.

Three per request (the API takes at most four): ① the end of the system (tools render before it, so
the entry covers both), ② the end of the history before this turn's request, ③ the last block of
the request. A person chatting gets one hour on ① and ② on Anthropic's own host or a listed verbatim
proxy; ③ always, and every other endpoint and background work, get the default five minutes. An
endpoint that refuses `ttl` gets it dropped, once, and the run record says so.
Documented Messages API shapes; no network, no key.
"""
import json

import httpx
import pytest

from arslan import execution_budget
from arslan.llm import param_heal, request_policy
from arslan.llm.adapter import LLMAdapter
from arslan.llm.cached_system import CachedSystem
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from server.orchestrator import tool_loop
from server.registry import executors
from tests.llm.test_k1b_anthropic_context import END, Search, refusal, tool_reply

LONG = {"type": "ephemeral", "ttl": "1h"}
SHORT = {"type": "ephemeral"}
HISTORY = [{"role": "user", "content": "earlier question"}, {"role": "assistant", "content": "earlier answer"}]
TWO_STEPS = [tool_reply("toolu_01", "one", "s1"), tool_reply("toolu_02", "two", "s2"), END]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("ARSLAN_TOOL_PROTOCOL", raising=False)
    param_heal.forget()
    yield
    param_heal.forget()


async def _resolve():
    return [{"key": "web_search", "description": "Search the web"}]


async def turn(monkeypatch, replies, *, long=False, base_url="", system="S", history=HISTORY,
               model="claude-opus-5-5", request="Find two sources"):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        reply = replies[len(sent) - 1]
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)
    adapter = LLMAdapter("anthropic", model)
    adapter._provider = AnthropicProvider(model, api_key="k", base_url=base_url,
                                          transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setitem(executors.EXECUTORS, "web_search", Search())
    with request_policy.prompt_cache(long=long):
        result = await tool_loop.run_native(system=system, user_content=request,
                                            history=list(history), emit=lambda e: None,
                                            on_chunk=lambda c: None, resolve_tools=_resolve)
    return result, sent


def markers(body):
    """(where, cache_control) for every breakpoint, in the order the API renders them."""
    found = [(("tool", t["name"]), t["cache_control"]) for t in body.get("tools") or [] if "cache_control" in t]
    system = body.get("system")
    found += [(("system", i), b["cache_control"])
              for i, b in enumerate(system if isinstance(system, list) else []) if "cache_control" in b]
    for m, message in enumerate(body["messages"]):
        content = message["content"]
        found += [((m, b), block["cache_control"])
                  for b, block in enumerate(content if isinstance(content, list) else []) if "cache_control" in block]
    return found


def unmarked(messages):
    """The messages as the model reads them: breakpoints removed, a lone text block as its string."""
    out = []
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            content = [{k: v for k, v in block.items() if k != "cache_control"} for block in content]
            if len(content) == 1 and content[0].get("type") == "text" and set(content[0]) == {"type", "text"}:
                content = content[0]["text"]
        out.append({**message, "content": content})
    return out


def last_block(body):
    return len(body["messages"]) - 1, len(body["messages"][-1]["content"]) - 1


# ── where the three go ─────────────────────────────────────────────────────────────────

async def test_system_end_history_end_and_tail_are_marked_on_every_step(monkeypatch):
    result, sent = await turn(monkeypatch, TWO_STEPS)
    assert result["final"] == "Done." and len(sent) == 3
    for body in sent:
        system_end = ("system", len(body["system"]) - 1)
        assert markers(body) == [(system_end, SHORT), ((1, 0), SHORT), (last_block(body), SHORT)]
        assert body["messages"][1]["content"][0]["text"] == "earlier answer"     # ② : the history's end


async def test_the_system_marker_sits_on_the_last_system_block(monkeypatch):
    _, sent = await turn(monkeypatch, [END], system=CachedSystem("STABLE", "\n\nROUTE"))
    system = sent[0]["system"]
    assert system[0] == {"type": "text", "text": "STABLE"}
    assert system[-1]["cache_control"] == SHORT and "ROUTE" in system[-1]["text"]
    assert "".join(b["text"] for b in system).startswith("STABLE\n\nROUTE")


async def test_without_history_there_is_no_history_marker(monkeypatch):
    _, sent = await turn(monkeypatch, [END], history=[])
    assert markers(sent[0]) == [(("system", 0), SHORT), ((0, 0), SHORT)]


async def test_markers_never_pile_up_and_what_was_sent_is_only_appended_to(monkeypatch):
    _, sent = await turn(monkeypatch, TWO_STEPS)
    for before, after in zip(sent, sent[1:]):
        assert len(markers(after)) == 3
        assert unmarked(after["messages"])[:len(before["messages"])] == unmarked(before["messages"])
    # The replayed assistant blocks (thinking + tool_use, byte for byte) carry no marker.
    replayed = sent[2]["messages"][3]["content"]
    assert all("cache_control" not in block for block in replayed)


async def test_a_block_list_request_is_marked_in_a_copy(monkeypatch):
    """An image turn's request is a block list whose text blocks the trajectory keeps; the tail marker
    of one step must not stay behind on them in the next (five markers is a 400)."""
    request = [{"type": "text", "text": "<turn_context>ref</turn_context>"}, {"type": "text", "text": "Find two"}]
    _, sent = await turn(monkeypatch, TWO_STEPS, request=request)
    assert [len(markers(body)) for body in sent] == [3, 3, 3]
    assert all("cache_control" not in block for body in sent[1:] for block in body["messages"][2]["content"])
    assert all("cache_control" not in block for block in request)


# ── how long they live ─────────────────────────────────────────────────────────────────

async def test_a_person_chatting_gets_an_hour_on_system_and_history(monkeypatch):
    _, sent = await turn(monkeypatch, TWO_STEPS, long=True)
    for body in sent:
        assert [cc for _, cc in markers(body)] == [LONG, LONG, SHORT]       # 1h before 5m, always


async def test_background_work_gets_five_minutes_everywhere(monkeypatch):
    _, sent = await turn(monkeypatch, TWO_STEPS, long=False)
    assert {json.dumps(cc) for body in sent for _, cc in markers(body)} == {json.dumps(SHORT)}


@pytest.mark.parametrize("base_url, model", [
    ("https://api.deepseek.com/anthropic", "claude-opus-5-5"),      # another Anthropic-protocol endpoint
    ("", "deepseek-v4"),                                              # not Claude
])
async def test_only_claude_on_anthropics_host_is_sent_a_ttl(monkeypatch, base_url, model):
    _, sent = await turn(monkeypatch, [END], long=True, base_url=base_url, model=model)
    assert "ttl" not in json.dumps(sent[0])
    assert [cc for _, cc in markers(sent[0])] == [SHORT, SHORT, SHORT]


async def test_a_listed_verbatim_proxy_gets_the_hour(monkeypatch):
    from arslan.llm.providers import anthropic_provider
    monkeypatch.setattr(anthropic_provider, "_FIRST_PARTY_HOSTS", frozenset({"127.0.0.1:8901"}))
    _, sent = await turn(monkeypatch, [END], long=True, base_url="http://127.0.0.1:8901/c/k3")
    assert [cc for _, cc in markers(sent[0])] == [LONG, LONG, SHORT]


async def test_a_refused_ttl_is_dropped_and_noted_once(monkeypatch):
    refused = refusal("messages.1.content.0.cache_control.ttl: Extra inputs are not permitted")
    with execution_budget.scope() as budget:
        result, sent = await turn(monkeypatch, [refused, tool_reply("toolu_01", "one", "s1"), END], long=True)
    assert result["final"] == "Done."
    assert "ttl" in json.dumps(sent[0]) and all("ttl" not in json.dumps(body) for body in sent[1:])
    assert all(len(markers(body)) == 3 for body in sent[1:])                # the breakpoints stay
    events = budget.snapshot()["context_events"]
    assert [e["kind"] for e in events if e["kind"] == "cache_ttl_off"] == ["cache_ttl_off"]
    # Remembered for this endpoint+model: the next turn never sends it.
    _, again = await turn(monkeypatch, [END], long=True)
    assert "ttl" not in json.dumps(again[0])


def test_param_heal_drops_ttl_from_every_marker_and_keeps_the_markers():
    payload = {"system": [{"type": "text", "text": "S", "cache_control": dict(LONG)}],
               "messages": [{"role": "user", "content": [{"type": "text", "text": "q", "cache_control": dict(LONG)}]},
                            {"role": "assistant", "content": "a"},
                            {"role": "user", "content": [{"type": "text", "text": "r", "cache_control": dict(SHORT)}]}]}
    response = httpx.Response(400, json={"type": "error", "error": {
        "type": "invalid_request_error", "message": "system.0.cache_control.ttl: Extra inputs are not permitted"}},
        request=httpx.Request("POST", "https://x.test"))
    heals = param_heal.Heals()
    assert param_heal.recover(httpx.HTTPStatusError("400", request=response.request, response=response),
                              payload, heals)
    assert "ttl" not in json.dumps(payload)
    assert markers(payload) == [(("system", 0), SHORT), ((0, 0), SHORT), ((2, 0), SHORT)]


# ── the prefix holds through wrapping up ──────────────────────────────────────────────

@pytest.mark.parametrize("limits", ["soft", "forced"])
async def test_wrapping_up_keeps_tools_and_system_and_only_appends(monkeypatch, limits):
    """Card acceptance: within a turn each request is a prefix of the next, the wrap-up steps too.
    soft: past the soft limit a research call is refused and the table stays; forced: the last step
    keeps the same table with tool_choice none."""
    from arslan.execution_budget import Budget, Limits, scope
    replies = [tool_reply("toolu_01", "one", "s1"), tool_reply("toolu_02", "two", "s2"), END]
    if limits == "soft":
        budget = Budget(Limits(tool_calls=10), soft=Limits(tool_calls=1))
    else:                                       # the hard limit after one call: a forced last step
        budget, replies = Budget(Limits(tool_calls=1)), replies[:1] + [END]
    with scope(budget):
        result, sent = await turn(monkeypatch, replies)
    assert result["final"] == "Done."
    assert len({json.dumps(body["tools"]) for body in sent}) == 1
    assert len({json.dumps(body["system"]) for body in sent}) == 1
    for before, after in zip(sent, sent[1:]):
        assert unmarked(after["messages"])[:len(before["messages"])] == unmarked(before["messages"])
    if limits == "forced":
        assert sent[-1]["tool_choice"] == {"type": "none"}
