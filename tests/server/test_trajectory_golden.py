"""0.1.49 S2: the exact model inputs run_native produces today, pinned.

Recorded at 4cc7af79, before the neutral-trajectory refactor (S3). After S3 the
legacy renderer (test doubles, Anthropic, ARSLAN_TOOL_PROTOCOL=legacy) and the
Gemini renderer must reproduce these payloads byte for byte: that is the proof
the refactor changed representation, not behaviour.

Regenerate ONLY on purpose: ARSLAN_UPDATE_GOLDEN=1 pytest tests/server/test_trajectory_golden.py
"""
import json
import os
from pathlib import Path

import pytest

from server.orchestrator import tool_loop

GOLDEN = Path(__file__).parent / "golden" / "legacy_payloads.json"


class _Resp:
    def __init__(self, content=None, tool_calls=None, provider_content=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.provider_content = provider_content


class _Recorder:
    def __init__(self, replies):
        self._r = list(replies)
        self.calls = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.calls.append({"system": system, "user": user, "history": history,
                           "tools": None if tools is None else [t["function"]["name"] for t in tools]})
        return self._r.pop(0)


def _tc(name, args, cid="c1", provider_id=None):
    call = {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}
    if provider_id:
        call["provider_id"] = provider_id
    return call


async def _resolve():
    return [{"key": "web_search", "description": "search the web"},
            {"key": "read_file", "description": "read a file"}]


class _Search:
    def __init__(self):
        self.n = 0

    async def execute(self, args):
        self.n += 1
        return {"ok": True, "summary": "2 results",
                "results": [{"title": f"result for {args.get('query')}", "url": "https://example.test/a"}]}


class _SameSearch:
    async def execute(self, args):
        return {"ok": True, "summary": "1 result", "results": [{"title": "same"}]}


SCENARIOS = {
    "one_call": dict(replies=[
        _Resp("looking", [_tc("web_search", {"query": "lighthouse"})]),
        _Resp("Lighthouses guide ships.")]),
    "parallel_with_invalid_args": dict(replies=[
        _Resp(None, [_tc("web_search", {"query": "a"}, "c1"), _tc("read_file", {}, "c2")]),
        _Resp("done")]),
    "unknown_tool": dict(replies=[
        _Resp(None, [_tc("no_such_tool", {"x": 1})]),
        _Resp("cannot")]),
    "forced_after_budget": dict(replies=[
        _Resp(None, [_tc("web_search", {"query": "q"})]),
        _Resp("final from forced step")], kwargs={"max_tool_calls": 1}),
    "answer_bounce_protocol_text": dict(replies=[
        _Resp('Let me search {"tool": "web_search", "args": {"query": "x"}}'),
        _Resp("Plain honest answer.")]),
    "repeats_until_stopped": dict(replies=[
        _Resp(None, [_tc("web_search", {"query": f"q{i}"})]) for i in range(5)] + [_Resp("blocked summary")],
        search=_SameSearch),
    "with_prior_history": dict(replies=[
        _Resp(None, [_tc("web_search", {"query": "follow up"})]),
        _Resp("answer")], history=[{"role": "user", "content": "earlier question"},
                                   {"role": "assistant", "content": "earlier answer"}]),
    "gemini_provider_pairs": dict(replies=[
        _Resp("narration", [_tc("web_search", {"query": "g"}, "gemini_0", provider_id="fc-1")],
              provider_content={"provider": "gemini", "parts": [
                  {"functionCall": {"id": "fc-1", "name": "web_search", "args": {"query": "g"}},
                   "thoughtSignature": "sig"}]}),
        _Resp("gemini answer")]),
}


async def _run(name, monkeypatch):
    spec = SCENARIOS[name]
    adapter = _Recorder(spec["replies"])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", spec.get("search", _Search)())
    result = await tool_loop.run_native(
        system="SYS", user_content=f"task for {name}", history=spec.get("history", []),
        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=_resolve,
        **spec.get("kwargs", {}))
    return {"calls": adapter.calls, "final": result.get("final")}


async def _presearch(monkeypatch):
    from server.services import tool_intent

    class _Intent:
        needs, tool, query = True, "web_search", "pre query"

    async def classify(*_a, **_k):
        return _Intent()
    monkeypatch.setattr(tool_intent, "classify", classify)
    adapter = _Recorder([_Resp(None, [_tc("web_search", {"query": "then"})]), _Resp("after presearch")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Search())
    result = await tool_loop.run_native(
        system="SYS", user_content="task for presearch", history=[], emit=lambda e: None,
        on_chunk=lambda c: None, resolve_tools=_resolve, force_tools=True)
    return {"calls": adapter.calls, "final": result.get("final")}


@pytest.mark.asyncio
async def test_run_native_model_inputs_match_golden(monkeypatch):
    recorded = {}
    for name in SCENARIOS:
        with monkeypatch.context() as m:
            recorded[name] = await _run(name, m)
    with monkeypatch.context() as m:
        recorded["presearch"] = await _presearch(m)
    text = json.dumps(recorded, ensure_ascii=False, indent=1, sort_keys=True, default=str)
    if os.environ.get("ARSLAN_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(text + "\n", encoding="utf-8")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for name, value in json.loads(text).items():
        assert value == golden[name], f"model inputs changed for scenario {name}"
    assert set(golden) == set(recorded)
