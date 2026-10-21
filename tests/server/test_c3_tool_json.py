"""C3: one measure for the tool table a request sends (card C3; K7 reuses it for its ≤ 12k check).

The measure is the table run_native hands the model adapter, as JSON without ASCII escapes, counted in
characters. This test pins that the helper counts exactly what a request carries, not a copy of it.
"""
import json

from server.orchestrator import tool_loop
from tests.server import test_trajectory_golden as golden
from tests.server.tool_json import rendered_tool_json_chars

WIRED = [
    {"key": "web_search", "description": "搜索网页", "input_schema": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"key": "read_file", "description": "Read a file."},
]


class _Keeper:
    """A native adapter that keeps the tool table it is sent, whole."""

    def __init__(self):
        self.tools = None

    def native_trajectory(self):
        return True

    async def chat_trajectory(self, system, messages, tools=None, tool_choice=None, **kw):
        self.tools = tools
        return golden._Resp("ok")


async def test_the_measure_is_what_a_request_sends(monkeypatch):
    adapter = _Keeper()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    golden._pin_workspace(monkeypatch)

    async def resolve():
        return WIRED
    await tool_loop.run_native(system="SYS", user_content="hi", history=[], emit=lambda e: None,
                               on_chunk=lambda c: None, resolve_tools=resolve, allow_escalation=False)
    sent = len(json.dumps(adapter.tools, ensure_ascii=False))
    assert rendered_tool_json_chars(WIRED) == sent
    assert "搜索网页" in json.dumps(adapter.tools, ensure_ascii=False)   # characters, not \u escapes
