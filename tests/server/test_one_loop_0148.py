"""0.1.48: every message reaches the agent and its tools; nothing answers in its place.

The pre-turn router this replaces could answer instead of the agent: "add today's
to-dos to Reminders" was classified as "connect an MCP" and came back as a canned
"no preset for that connector" without a single tool being offered to the model."""
import pytest

from server.orchestrator import arslan, tool_loop
from server.services import turn_facts
from tests.server.test_arslan_loop import _LLMResp, _NativeAdapter, _events, maker  # noqa: F401


class _SeeingAdapter(_NativeAdapter):
    """Records the tool names the model was offered on each call."""
    def __init__(self, replies):
        super().__init__(replies)
        self.offered = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.offered.append([t["function"]["name"] for t in (tools or [])])
        return await super().chat(system, user, history, tools, temperature)


async def _no_facts(conv, msg):
    return []


@pytest.mark.parametrize("message", ["把今天的待办加进提醒事项", "详细步骤 你给我列出来", "connect my GitHub"])
async def test_every_message_reaches_the_agent_with_its_tools(maker, monkeypatch, message):  # noqa: F811
    adapter = _SeeingAdapter([_LLMResp(content="On it.")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    monkeypatch.setattr(turn_facts, "extract", _no_facts)
    events = []
    await arslan.handle_user_message("c1", message, _events(events))
    assert adapter.offered, "the agent loop never ran"
    assert "web_search" in adapter.offered[0] and "suggest_connector" in adapter.offered[0]
    text = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert "don't have a preset" not in text and text == "On it."


async def test_facts_are_looked_for_after_the_answer_not_before(maker, monkeypatch):  # noqa: F811
    order = []

    class _Adapter(_NativeAdapter):
        async def chat(self, *a, **k):
            order.append("answer")
            return await super().chat(*a, **k)

    async def _facts(conv, msg):
        order.append("facts")
        return []

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _Adapter([_LLMResp(content="ok")]))
    monkeypatch.setattr(turn_facts, "extract", _facts)
    await arslan.handle_user_message("c1", "I prefer short answers", _events([]))
    assert order == ["answer", "facts"]


async def test_a_failing_fact_step_never_breaks_the_turn(maker, monkeypatch):  # noqa: F811
    async def _boom(conv, msg):
        raise RuntimeError("provider down")

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _NativeAdapter([_LLMResp(content="fine")]))
    monkeypatch.setattr(turn_facts, "extract", _boom)
    events = []
    await arslan.handle_user_message("c1", "hi", _events(events))
    assert any(e["type"] == "stream_end" for e in events)
    assert not any(e["type"] == "error" for e in events)


@pytest.mark.parametrize("flag", ["temporary", "no_memory", "no_learning"])
async def test_no_facts_in_a_private_conversation(maker, monkeypatch, flag):  # noqa: F811
    from dataclasses import replace

    from server.services import personal_context
    called = []

    async def _facts(conv, msg):
        called.append(1)
        return []

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _NativeAdapter([_LLMResp(content="ok")]))
    monkeypatch.setattr(turn_facts, "extract", _facts)
    base = personal_context.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c1")
    monkeypatch.setattr(personal_context, "current", lambda: replace(base, **{flag: True}))
    await arslan.handle_user_message("c1", "my salary is 10k", _events([]))
    assert called == []


def test_fact_replies_are_parsed_defensively():
    assert turn_facts.parse("not json") == []
    assert turn_facts.parse('{"new_facts": [{"content": "  a  b "}, {"content": ""}, 3]}') == [
        {"content": "a b", "sensitive": False}]
    many = '{"new_facts": [' + ",".join('{"content": "f%d"}' % i for i in range(9)) + "]}"
    assert len(turn_facts.parse(many)) == turn_facts.MAX_FACTS
