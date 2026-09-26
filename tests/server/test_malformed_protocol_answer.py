"""Malformed textual tool requests are neither answers nor executable calls."""
import pytest

from arslan.models import LLMResponse
from server.orchestrator import tool_loop


@pytest.mark.parametrize("text", [
    '{"tool":"write_file","args":{"content":"auth mode = "none""}}',
    '准备写入：{"tool": "write_file", "args": {"path": "comparison.md",',
    '```json\n{"functionCall": {"name": "write_file",',
])
def test_malformed_protocol_is_still_not_a_final_answer(text):
    assert tool_loop._embeds_protocol(text)


@pytest.mark.parametrize("text", ['{"name":"tool","value":12}', 'The tool failed; no file was saved.'])
def test_ordinary_json_and_prose_remain_valid(text):
    assert not tool_loop._embeds_protocol(text)


async def test_malformed_write_is_not_dispatched_or_streamed(monkeypatch):
    replies = iter([
        '{"tool":"write_file","args":{"content":"auth = "none""}}',
        'The requested file has not been saved.',
    ])

    class Adapter:
        async def chat(self, *args, **kwargs):
            return LLMResponse(content=next(replies), usage={})

    class NeverWrite:
        async def execute(self, args):
            pytest.fail("textual malformed tool call must not dispatch")

    async def tools():
        return [{"key": "write_file", "description": "Save approved file"}]

    monkeypatch.setitem(tool_loop.EXECUTORS, "write_file", NeverWrite())
    chunks = []
    result = await tool_loop.run_native(system="Fixture", user_content="Save comparison.md", history=[],
        resolve_tools=tools, emit=lambda _: None, on_chunk=chunks.append, adapter_override=Adapter())
    assert not result["tool_trace"]
    assert '"tool"' not in "".join(chunks)
    assert result["final"] == "The requested file has not been saved."


@pytest.mark.parametrize("allowed", [True, False])
@pytest.mark.parametrize("malformed", [True, False])
async def test_text_protocol_can_be_corrected_only_by_native_call(monkeypatch, allowed, malformed):
    emitted, dispatched, confirmations, payloads = [], [], [], []
    text = ('{"tool":"write_file","args":{"path":"comparison.md","content":"mode = "none""}}'
            if malformed else '{"tool":"write_file","args":{"path":"comparison.md","content":"proposed"}}')

    class Adapter:
        async def chat(self, system, user, history=None, tools=None, **kwargs):
            payloads.append({"tools": tools, "history": history, "user": user})
            step = len(payloads)
            if step == 1:
                return LLMResponse(content=text, usage={})
            if step == 2:
                assert tools is not None, "correction must retain the native tool channel within budget"
                return LLMResponse(content="", usage={}, tool_calls=[{
                    "id": "corrected", "type": "function", "function": {"name": "write_file",
                    "arguments": {"path": "comparison.md", "content": "corrected native content"}}}])
            return LLMResponse(content="The file was saved." if allowed else "Write was declined; no file was saved.", usage={})

    class Writer:
        async def execute(self, args):
            dispatched.append(args)
            return {"ok": True}

    async def tools():
        return [{"key": "write_file", "description": "Write an approved file"}]

    async def confirm(tool, path):
        confirmations.append((tool, path))
        return allowed

    monkeypatch.setitem(tool_loop.EXECUTORS, "write_file", Writer())
    result = await tool_loop.run_native(system="Fixture", user_content="Save comparison.md", history=[],
        resolve_tools=tools, emit=lambda _: None, on_chunk=emitted.append, adapter_override=Adapter(),
        confirm_workspace_write=confirm)
    assert len(payloads) == 3
    assert confirmations == [("write_file", "comparison.md")]
    assert dispatched == ([{"path": "comparison.md", "content": "corrected native content"}] if allowed else [])
    assert text not in str(payloads[1]["history"]) and text not in "".join(emitted)
    assert len(result["tool_trace"]) == 1


async def test_protocol_correction_cannot_extend_request_budget():
    from arslan.execution_budget import Budget, BudgetExceeded, Limits, scope
    budget = Budget(Limits(model_requests=2))
    calls, chunks = [], []

    class Adapter:
        async def chat(self, *args, **kwargs):
            budget.model_request(100)  # Simulated provider admission, no network.
            calls.append(kwargs.get("tools"))
            return LLMResponse(content='{"tool":"write_file",', usage={})

    async def tools():
        return [{"key": "write_file", "description": "Write an approved file"}]

    with scope(budget), pytest.raises(BudgetExceeded, match="model_requests"):
        await tool_loop.run_native(system="Fixture", user_content="Save comparison.md", history=[],
            resolve_tools=tools, emit=lambda _: None, on_chunk=chunks.append, adapter_override=Adapter())
    assert len(calls) == budget.model_requests == 2 and budget.tool_calls == 0
    assert not chunks
