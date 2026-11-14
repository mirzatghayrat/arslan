"""Malformed textual tool requests are neither answers nor executable calls."""
import pytest

from arslan.models import LLMResponse
from server.orchestrator import answer_guards, tool_loop


@pytest.mark.parametrize("text", [
    '{"tool":"write_file","args":{"content":"auth mode = "none""}}',
    '准备写入：{"tool": "write_file", "args": {"path": "comparison.md",',
    '```json\n{"functionCall": {"name": "write_file",',
])
def test_malformed_protocol_is_still_not_a_final_answer(text):
    assert answer_guards._embeds_protocol(text)


@pytest.mark.parametrize("text", ['{"name":"tool","value":12}', 'The tool failed; no file was saved.'])
def test_ordinary_json_and_prose_remain_valid(text):
    assert not answer_guards._embeds_protocol(text)


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




async def test_protocol_correction_cannot_extend_request_budget(monkeypatch):
    """A protocol correction never buys a model request past the cap. Since #896 the chat turn the cap stops ends
    with the host's closing (no model call) instead of raising; the malformed request itself is still not shown."""
    from arslan.execution_budget import Budget, Limits, scope
    from server.services import runtime_messages

    async def en():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", en)
    budget = Budget(Limits(model_requests=2))
    calls, chunks = [], []

    class Adapter:
        async def chat(self, *args, **kwargs):
            calls.append(kwargs.get("tools"))  # every attempt, before admission: a refused extra one counts too
            budget.model_request(100)  # Simulated provider admission, no network.
            return LLMResponse(content='{"tool":"write_file",', usage={})

    async def tools():
        return [{"key": "write_file", "description": "Write an approved file"}]

    with scope(budget):
        result = await tool_loop.run_native(system="Fixture", user_content="Save comparison.md", history=[],
            resolve_tools=tools, emit=lambda _: None, on_chunk=chunks.append, adapter_override=Adapter())
    assert len(calls) == budget.model_requests == 2 and budget.tool_calls == 0
    assert budget.stop_reason == "model_requests"
    assert result["stop_reason"] == "task_budget_exhausted"
    assert result["final"] == "".join(chunks)
    assert '"tool"' not in result["final"]
    assert "work limit (model requests)" in result["final"]
    assert result["final"].endswith("Left: the request itself, Save comparison.md")
