"""0.1.49 S8: tool-call mistakes become precise model input, never guesses."""
import pytest

from server.orchestrator import tool_loop
from tests.server import test_trajectory_golden as golden


@pytest.mark.parametrize("raw,expected", [
    ('{"path": "a.md", "content": "line1\nline2"}', {"path": "a.md", "content": "line1\nline2"}),  # raw newline
    ("", {}), ("   ", {}),
])
def test_parse_arguments_repairs_only_control_characters(raw, expected):
    assert tool_loop._parse_arguments(raw) == (expected, None)


@pytest.mark.parametrize("raw,fragment", [
    ('{"path": "a.md",}', "at character"), ("[1, 2]", "expected a JSON object"), ("{'path': 1}", "at character"),
])
def test_parse_arguments_reports_what_it_cannot_parse(raw, fragment):
    value, problem = tool_loop._parse_arguments(raw)
    assert value is None and fragment in problem


SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}, "count": {"type": "integer"},
                                           "tags": {"type": ["array", "null"]}, "flag": {"type": "boolean"}},
          "required": ["path"]}


@pytest.mark.parametrize("args,problem", [
    ({"path": "a"}, None),
    ({"path": "a", "tags": None}, None),
    ({}, "missing required 'path' (string)"),
    ({"path": 3}, "'path' must be string"),
    ({"path": "a", "count": True}, "'count' must be integer"),       # bool is not an integer here
    ({"path": "a", "count": 2.5}, "'count' must be integer"),
    ({"path": "a", "flag": "yes"}, "'flag' must be boolean"),
    ({"path": "a", "extra": object()}, None),                          # unknown keys: executor decides
])
def test_schema_problem(args, problem):
    assert tool_loop._schema_problem(args, SCHEMA) == problem


def test_permissive_or_missing_schema_checks_nothing():
    assert tool_loop._schema_problem({"x": 1}, None) is None
    assert tool_loop._schema_problem({"x": 1}, {"type": "object"}) is None


async def _run_one(monkeypatch, call, executed):
    class Search:
        async def execute(self, args):
            executed.append(args)
            return {"ok": True, "results": [args]}
    adapter = golden._Recorder([golden._Resp(None, [call]), golden._Resp("done")])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", Search())
    result = await tool_loop.run_native(system="S", user_content="t", history=[], emit=lambda e: None,
                                        on_chunk=lambda c: None, resolve_tools=golden._resolve)
    return result, adapter.calls[1]["user"]


async def test_raw_newline_arguments_are_repaired_and_executed(monkeypatch):
    executed = []
    call = {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": '{"query": "a\nb"}'}}
    await _run_one(monkeypatch, call, executed)
    assert executed == [{"query": "a\nb"}]


async def test_unparseable_arguments_are_not_executed_with_empty_args(monkeypatch):
    """The pre-0.1.49 loop replaced unparseable arguments with {} and ran the tool."""
    executed = []
    call = {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": '{"query": "a",,}'}}
    result, feedback = await _run_one(monkeypatch, call, executed)
    assert executed == []
    assert result["tool_trace"][0]["result"]["code"] == "invalid_arguments_json"
    assert "not valid JSON" in feedback and "at character" in feedback


async def test_schema_violation_is_explained_and_not_executed(monkeypatch):
    executed = []
    call = {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": {"q": "x"}}}
    result, feedback = await _run_one(monkeypatch, call, executed)
    assert executed == [] and "missing required 'query' (string)" in feedback
    assert "EXTERNAL_WEB_CONTENT" not in feedback.split("Use this to continue")[0]  # our words, trusted


async def test_unknown_tool_lists_close_available_names(monkeypatch):
    executed = []
    call = {"id": "c1", "type": "function", "function": {"name": "web_serch", "arguments": {"query": "x"}}}
    _, feedback = await _run_one(monkeypatch, call, executed)
    assert "available tools include: web_search" in feedback and executed == []


async def test_progress_note_appears_once_the_loop_detector_counts():
    from arslan.runtime_policy import ProgressPolicy
    policy = ProgressPolicy()
    policy.stalled = 2
    assert "2 of 4 steps without progress" in tool_loop._progress_note(policy)
