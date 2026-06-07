"""Tests for ArslanTool base class and ToolResult."""
import pytest

from arslan.tools.base import ArslanTool, ToolResult


# ── Concrete implementations for testing ─────────────────────────────────────

class DummyTool(ArslanTool):
    name = "dummy"
    description = "A dummy tool for testing"
    tags = ["test", "dummy"]
    input_schema = {"type": "object", "properties": {"value": {"type": "string"}}}
    output_schema = {"type": "object", "properties": {"result": {"type": "string"}}}

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=True, data={"result": params.get("value", "ok")})

    async def health_check(self) -> bool:
        return True


class FailingTool(ArslanTool):
    name = "failing"
    description = "A tool that always fails"
    tags = ["test", "failing"]
    input_schema = {}
    output_schema = {}

    async def execute(self, params: dict) -> ToolResult:
        return ToolResult(success=False, error="intentional failure")

    async def health_check(self) -> bool:
        return False


# ── ToolResult tests ──────────────────────────────────────────────────────────

def test_tool_result_success_defaults():
    result = ToolResult(success=True)
    assert result.success is True
    assert result.data == {}
    assert result.error is None


def test_tool_result_failure_carries_error():
    result = ToolResult(success=False, error="something went wrong")
    assert result.success is False
    assert result.error == "something went wrong"


def test_tool_result_success_carries_data():
    result = ToolResult(success=True, data={"key": "value"})
    assert result.data == {"key": "value"}


# ── DummyTool execute tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dummy_tool_execute_returns_success():
    tool = DummyTool()
    result = await tool.execute({"value": "hello"})
    assert isinstance(result, ToolResult)
    assert result.success is True


@pytest.mark.asyncio
async def test_dummy_tool_execute_returns_data():
    tool = DummyTool()
    result = await tool.execute({"value": "hello"})
    assert result.data == {"result": "hello"}


@pytest.mark.asyncio
async def test_dummy_tool_health_check_returns_true():
    tool = DummyTool()
    assert await tool.health_check() is True


# ── FailingTool tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failing_tool_execute_returns_failure():
    tool = FailingTool()
    result = await tool.execute({})
    assert result.success is False


@pytest.mark.asyncio
async def test_failing_tool_execute_has_error_message():
    tool = FailingTool()
    result = await tool.execute({})
    assert result.error == "intentional failure"


@pytest.mark.asyncio
async def test_failing_tool_health_check_returns_false():
    tool = FailingTool()
    assert await tool.health_check() is False


# ── metadata() tests ──────────────────────────────────────────────────────────

def test_metadata_returns_dict():
    tool = DummyTool()
    meta = tool.metadata()
    assert isinstance(meta, dict)


def test_metadata_contains_name():
    tool = DummyTool()
    assert tool.metadata()["name"] == "dummy"


def test_metadata_contains_description():
    tool = DummyTool()
    assert tool.metadata()["description"] == "A dummy tool for testing"


def test_metadata_contains_tags():
    tool = DummyTool()
    assert tool.metadata()["tags"] == ["test", "dummy"]


def test_metadata_contains_input_schema():
    tool = DummyTool()
    assert "input_schema" in tool.metadata()


def test_metadata_contains_output_schema():
    tool = DummyTool()
    assert "output_schema" in tool.metadata()


def test_metadata_exact_keys():
    tool = DummyTool()
    meta = tool.metadata()
    assert set(meta.keys()) == {"name", "description", "tags", "input_schema", "output_schema"}
