"""K8b C3: Claude's progress updates between tool calls (card K8, the optional item; ⓪Plan's Q4).

Opus 5.5, Sonnet 5.5, Fable 5 / 5.1 and Mythos 5.1 write a short update before a tool call (what they found,
what they do next) as a thinking block, empty unless the request asks `thinking.display: "updates"` (beta
thinking-display-updates-2026-08-18; claude-api model-migration guide). Asked only of Claude on Anthropic's
host or a listed first-party proxy (never a beta header to another router); refused, it is dropped with its
beta and the request resent. Each update is shown as a `note` before the calls it introduces: never part of
the answer, the stored text, speech or the phone (the Bridge maps no `note`).
"""
import json

import httpx
import pytest

from arslan.llm import param_heal
from arslan.llm.providers.anthropic_provider import UPDATES_BETA, AnthropicProvider
from tests.llm.test_k8b_anthropic_stream import block, end, piece, sse, start, stop, whole
from tests.server.test_k8b_claude_streaming import _Search, turn  # noqa: F401 — the Claude turn fixture

BASE = "https://api.anthropic.com/v1"
NATIVE = [{"role": "system", "content": "S", "_trajectory": True}, {"role": "user", "content": "hi"}]


def _payload(model, base=BASE):
    return AnthropicProvider(model, api_key="k", base_url=base)._payload(NATIVE, 0.7, None)


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-mythos-5-1"])
def test_the_models_that_write_updates_are_asked_for_them_with_their_beta(model):
    payload = _payload(model)
    assert payload["thinking"]["display"] == "updates" and payload["thinking"]["type"] == "adaptive"
    assert "block_binding" in payload["thinking"] and UPDATES_BETA in payload["_betas"]


def test_fable_5_which_binds_nothing_gets_adaptive_thinking_with_updates():
    payload = _payload("claude-fable-5")
    assert payload["thinking"] == {"type": "adaptive", "display": "updates"} and payload["_betas"] == [
        "context-management-2025-06-27", UPDATES_BETA]


@pytest.mark.parametrize("model,base", [("claude-opus-5-5", "https://claude-router.example/v1"),
                                        ("claude-haiku-5-5", BASE), ("claude-sonnet-5", BASE)])
def test_others_are_not_asked(model, base):
    payload = _payload(model, base)
    assert "display" not in (payload.get("thinking") or {}) and UPDATES_BETA not in (payload.get("_betas") or [])


async def test_an_endpoint_that_refuses_updates_gets_the_request_again_without_them():
    param_heal.forget()
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append((body, request.headers.get("anthropic-beta", "")))
        if "display" in body.get("thinking", {}):
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "thinking.display: unexpected value 'updates'"}})
        return httpx.Response(200, json=whole([{"type": "text", "text": "fine"}]))
    provider = AnthropicProvider("claude-opus-5-5", api_key="k", base_url=BASE, transport=httpx.MockTransport(handler))
    response = await provider.chat(NATIVE)
    assert response.content == "fine" and len(sent) == 2
    assert "display" not in sent[1][0]["thinking"] and UPDATES_BETA not in sent[1][1]
    assert sent[1][0]["thinking"]["block_binding"]                      # the rest of the thinking stays
    assert not provider.writes_updates()                                  # remembered: not asked again
    param_heal.forget()


def test_sonnet_5_5s_between_tools_switch_never_gets_updates():
    from arslan.llm.request_policy import bounded_critique
    token = bounded_critique.set(True)
    try:
        payload = _payload("claude-sonnet-5-5")
    finally:
        bounded_critique.reset(token)
    assert payload["thinking"] == {"type": "between_tools"} and UPDATES_BETA not in (payload.get("_betas") or [])


def test_notes_come_only_from_a_reply_whose_request_carried_updates():
    from types import SimpleNamespace
    from server.orchestrator import tool_loop
    blocks = [{"type": "thinking", "thinking": "a summary of reasoning", "signature": "s"}]
    asked = SimpleNamespace(continuation={"protocol": "anthropic", "content": blocks, "updates": True})
    not_asked = SimpleNamespace(continuation={"protocol": "anthropic", "content": blocks})
    assert tool_loop._progress_updates(None, asked) == ["a summary of reasoning"]
    assert tool_loop._progress_updates(None, not_asked) == []


async def test_a_reply_to_a_request_that_lost_updates_on_the_way_gives_no_notes():
    """⓪Plan's review: the endpoint refused `display`, param_heal resent without it; the answered request
    did not ask, so its thinking text (whatever it is) is never shown as an update."""
    param_heal.forget()

    def handler(request):
        body = json.loads(request.content)
        if "display" in body.get("thinking", {}):
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "thinking.display: unexpected value 'updates'"}})
        return httpx.Response(200, json=whole([{"type": "thinking", "thinking": "private reasoning", "signature": "s"},
                                               {"type": "tool_use", "id": "t1", "name": "read_file", "input": {}}],
                                              "tool_use"))
    provider = AnthropicProvider("claude-opus-5-5", api_key="k", base_url=BASE, transport=httpx.MockTransport(handler))
    response = await provider.chat(NATIVE)
    assert "updates" not in response.continuation
    from server.orchestrator import tool_loop
    assert tool_loop._progress_updates(None, response) == []
    param_heal.forget()


async def test_an_update_is_a_note_before_its_tool_call_and_never_part_of_the_answer(turn):  # noqa: F811
    update = "Found the tide tables; checking today's row next."
    first = sse(start(),
                block(0, {"type": "thinking", "thinking": "", "signature": ""}),
                piece(0, type="thinking_delta", thinking=update), piece(0, type="signature_delta", signature="s1"),
                stop(0),
                block(1, {"type": "thinking", "thinking": "", "signature": ""}),
                piece(1, type="thinking_delta", thinking="This part of the response was interrupted before it finished."),
                piece(1, type="signature_delta", signature="s2"), stop(1),
                block(2, {"type": "tool_use", "id": "toolu_1", "name": "web_search", "input": {}}),
                piece(2, type="input_json_delta", partial_json='{"query": "tides"}'), stop(2), end("tool_use"))
    answer = sse(start(), block(0, {"type": "text", "text": ""}),
                 piece(0, type="text_delta", text="High tide is at noon today."), stop(0), end())
    result, chunks, events, bodies = await turn([first, answer], tools=("web_search",),
                                                executors={"web_search": _Search()})
    kinds = [(e["type"], e.get("text") or e.get("tool")) for e in events if e["type"] in ("note", "tool_call")]
    assert kinds[:2] == [("note", update), ("tool_call", "web_search")]
    assert not any("interrupted before it finished" in (e.get("text") or "") for e in events)
    assert update not in "".join(chunks) and update not in result["final"]
    assert next(m for m in bodies[1]["messages"] if m["role"] == "assistant")["content"][0]["thinking"] == update
