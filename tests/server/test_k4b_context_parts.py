"""K4b: the context ring's breakdown, server side (master plan K4 ⑦, ⓪Plan Q8).

Just before each request is sent, its parts are estimated with the one estimator: the system text, the
tools, the turn's reference block (memory and context), earlier turns, and this turn (the user's words,
tool calls and results, the status block). The last request's parts ride in stream_end's usage as
`context_parts`; the ring's total stays the provider's `last_input`.
"""
import copy
import json

from arslan.context_budget import estimate_tokens
from arslan.llm import usage_sink
from server.orchestrator import tool_loop, turn_context
from tests.server import test_trajectory_golden as golden

PARTS = {"system", "tools", "context", "history", "turn"}
BLOCK = turn_context.wrap("Known facts: the user keeps receipts in ~/Arslan/receipts. " * 40)
HISTORY = [{"role": "user", "content": "What did we decide about the receipts folder last week? " * 10},
           {"role": "assistant", "content": "We decided to sort them by month and keep the PDFs. " * 10}]


class _Recorder:
    def __init__(self, replies):
        self._r = list(replies)
        self.calls = []

    def native_trajectory(self):
        return True

    async def chat_trajectory(self, system, messages, tools=None, tool_choice=None, **kw):
        self.calls.append({"system": system, "messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools),
                           "parts": copy.deepcopy(usage_sink.context_parts())})
        return self._r.pop(0)


async def _run(monkeypatch, user_content, history):
    adapter = _Recorder([golden._Resp(None, [golden._tc("web_search", {"query": "receipts"}, "s1")]),
                         golden._Resp("Sorted.")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", golden._Search())

    async def resolve():
        return [{"key": "web_search", "description": "search"}]
    with usage_sink.collecting():
        await tool_loop.run_native(system="Be helpful. " * 50, user_content=user_content, history=history,
                                   emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=resolve)
        return adapter.calls, usage_sink.context_parts()


async def test_each_request_is_measured_as_it_is_sent(monkeypatch):
    calls, last = await _run(monkeypatch, turn_context.prepend(BLOCK, "Sort my receipts by month."), HISTORY)
    first, second = (call["parts"] for call in calls)
    assert set(first) == PARTS and all(isinstance(v, int) and v >= 0 for v in first.values())
    for call in calls:
        assert call["parts"]["system"] == estimate_tokens(call["system"])
        assert call["parts"]["tools"] == estimate_tokens(json.dumps(call["tools"], ensure_ascii=False))
        assert abs(call["parts"]["context"] - estimate_tokens(BLOCK + "\n\n")) <= 1
    assert first["history"] > 0 and second["history"] == first["history"]
    assert second["turn"] > first["turn"]                         # the search's call and result are this turn
    assert last == second                                         # what stream_end carries: the last request


async def test_a_plain_first_turn_has_no_context_and_no_history(monkeypatch):
    calls, last = await _run(monkeypatch, "Sort my receipts by month.", [])
    assert last["context"] == 0 and last["history"] == 0 and last["turn"] > 0


def test_the_reply_frame_carries_the_parts_or_none():
    from server.orchestrator import arslan
    parts = {"system": 900, "tools": 4000, "context": 300, "history": 1200, "turn": 2500}
    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=8000, tokens_out=50, model="m", provider="p")
        assert arslan._usage_frame(usage_sink.detail())["context_parts"] is None     # no request measured
        usage_sink.note_context_parts(parts)
        frame = arslan._usage_frame(usage_sink.detail())
    assert frame["context_parts"] == parts and frame["last_input"] == 8000
    assert usage_sink.context_parts() is None                       # nothing outlives the turn's scope
