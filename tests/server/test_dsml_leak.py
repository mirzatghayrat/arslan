"""DeepSeek sometimes writes its chat-template tool-call markup into content
instead of returning native tool_calls. Seen in the 0.1.49 paired bench
(arslan-T3-r2): the markup became the final answer. It must be treated as
protocol text: never shown as an answer, never executed."""
import pytest

from server.orchestrator import tool_loop
from tests.server import test_trajectory_golden as golden

LEAK = ("<｜｜DSML｜｜tool_calls>\n<｜｜DSML｜｜invoke name=\"web_extract\">\n"
        "<｜｜DSML｜｜parameter name=\"url\" string=\"true\">https://example.test/aapl</｜｜DSML｜｜parameter>\n"
        "</｜｜DSML｜｜invoke>\n</｜｜DSML｜｜tool_calls>")


@pytest.mark.parametrize("text", [
    LEAK, "Let me read it. " + LEAK, "<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>web_search",
    "<|DSML|tool_calls>",
])
def test_deepseek_template_markup_is_protocol_text(text):
    assert tool_loop._embeds_protocol(text)


@pytest.mark.parametrize("text", [
    "I made three tool calls and read two pages.", "The table is saved | source: SEC 10-K",
    "营收 | 净利润 | 来源",
])
def test_ordinary_prose_is_not(text):
    assert not tool_loop._embeds_protocol(text)


async def test_leaked_markup_is_bounced_not_shown(monkeypatch):
    executed, chunks = [], []

    class Search:
        async def execute(self, args):
            executed.append(args)
            return {"ok": True}
    adapter = golden._Recorder([golden._Resp(LEAK), golden._Resp("Revenue table saved.")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", Search())
    result = await tool_loop.run_native(system="S", user_content="t", history=[], emit=lambda e: None,
                                        on_chunk=chunks.append, resolve_tools=golden._resolve)
    assert result["final"] == "Revenue table saved."
    assert "DSML" not in "".join(chunks) and executed == []
    assert "not a native tool request" in adapter.calls[1]["user"]
