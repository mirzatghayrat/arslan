"""File argument contracts must not depend on a model guessing from prose."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.db.models import Setting
from server.orchestrator import arslan, tool_loop


async def test_production_file_tools_declare_required_arguments(execution_db, tmp_path):
    async with execution_db() as db:
        db.add(Setting(key="workspace_dir", value=str(tmp_path)))
        await db.commit()
    specs = tool_loop._native_tool_schemas(await arslan._arslan_tools(), allow_escalation=False)
    by_name = {item["function"]["name"]: item["function"]["parameters"] for item in specs}
    assert by_name["read_file"]["required"] == ["path"]
    assert by_name["write_file"]["required"] == ["path", "content"]
    assert by_name["write_file"]["properties"]["path"]["minLength"] == 1
    assert by_name["write_file"]["properties"]["content"]["type"] == "string"


@pytest.mark.parametrize("key,args", [("write_file", {"content": "x"}), ("read_file", {}),
    ("write_file", {"path": " ", "content": "x"}), ("write_file", {"path": "x", "content": 4}),
    ("read_file", {"path": 4})])
async def test_invalid_file_args_are_not_reported_as_user_decline(monkeypatch, key, args):
    model = SimpleNamespace(chat=AsyncMock(side_effect=[
        SimpleNamespace(content="", usage={}, tool_calls=[{"id": "call", "type": "function",
            "function": {"name": key, "arguments": args}}]),
        SimpleNamespace(content="Stopped after invalid arguments.", usage={}, tool_calls=[])]))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    executor = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("no file I/O")))
    monkeypatch.setitem(tool_loop.EXECUTORS, key, executor)
    confirm = AsyncMock(side_effect=AssertionError("invalid arguments must not ask the user"))

    async def tools():
        return [{"key": key, "description": "file operation"}]

    result = await tool_loop.run_native(system="S", user_content="synthetic", history=[],
        emit=lambda _: None, on_chunk=lambda _: None, resolve_tools=tools, confirm_workspace_write=confirm)
    assert result["tool_trace"][0]["result"]["code"] == "invalid_file_arguments"
    confirm.assert_not_called()
    executor.execute.assert_not_called()


def test_missing_numeric_values_are_not_assumed_positive():
    assert "do not assume zero, a positive sign, or a lower/upper bound" in arslan._WEB_TOOL_GUIDANCE
