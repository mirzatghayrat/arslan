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
