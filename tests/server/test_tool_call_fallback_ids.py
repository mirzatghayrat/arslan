"""A tool call the provider sends with no id, or with a repeated one, gets `call_<step>_<index>`.

K8a named the step's stream `step` inside the loop over steps, so these ids came out as
`call_<..._StepStream object at 0x...>_0`, or `call_None_0` where nothing streams. Such ids go back to the provider as
tool_call_id, and an address in an id is neither stable nor sure to be accepted."""
import types

import pytest

from server.orchestrator import tool_loop
from server.registry import executors


class _Model:
    _provider = None

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def native_trajectory(self):
        return True

    async def chat_trajectory(self, _system, messages, tools=None, tool_choice=None, **_own):
        self.sent = [call["id"] for message in messages for call in message.get("tool_calls") or []]
        return self.replies.pop(0)


def _reply(content, *ids):
    calls = [{"id": call_id, "function": {"name": "web_search", "arguments": {"query": f"q{index}"}}}
             for index, call_id in enumerate(ids)]
    return types.SimpleNamespace(content=content, tool_calls=calls, finish_reason="stop", continuation=None,
                                 provider_content=None)


class _Search:
    key = "web_search"

    async def execute(self, _args):
        return {"ok": True, "summary": "1 result", "results": [{"title": "t", "url": "https://example.test/a"}]}


@pytest.mark.parametrize("streams", [True, False])
async def test_a_call_with_no_usable_id_is_named_by_its_step(streams, monkeypatch):
    async def stream_setting(_a, _runtime):
        return streams

    async def tools():
        return [{"key": "web_search", "description": "search"}]
    monkeypatch.setattr(tool_loop, "_streams_answer", stream_setting)
    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Search())
    model = _Model([_reply(None, "", "dup"), _reply(None, "dup", ""), _reply("Done.")])
    await tool_loop.run_native(system="s", user_content="hi", history=[], emit=lambda _frame: None,
                               on_chunk=lambda _chunk: None, resolve_tools=tools, adapter_override=model,
                               allow_escalation=False)
    assert model.sent == ["call_0_0", "dup", "call_1_0", "call_1_1"]
