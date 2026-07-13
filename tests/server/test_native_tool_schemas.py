"""S0 — MCP tool schemas must reach the model.

The `input_schema` captured at MCP discovery and stored on `Tool` is the JSON Schema
the model needs to call the tool with the right argument names. Both native tool-list
builders — `_native_tool_schemas` (spawn path) and `_arslan_tools` (host path, whose
output flows through `_native_tool_schemas` via `run_native`) — must pass that schema
through as the OpenAI `function.parameters`, instead of an empty/permissive `{}` that
forces the model to guess argument names.
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, MCPServer, Tool, Toolset
from server.orchestrator.tool_loop import _native_tool_schemas

_MCP_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


def _params_for(schemas: list[dict], name: str) -> dict:
    for s in schemas:
        if s["type"] == "function" and s["function"]["name"] == name:
            return s["function"]["parameters"]
    raise AssertionError(f"{name} missing from schemas: {[s.get('function', {}).get('name') for s in schemas]}")


def test_mcp_tool_schema_reaches_model():
    """A wired MCP tool carrying a non-empty input_schema must expose it as parameters —
    NOT the permissive `{}` fallback."""
    wired = [{"key": "mcp_1__search", "description": "search docs", "input_schema": _MCP_SCHEMA}]
    schemas = _native_tool_schemas(wired, allow_escalation=False)
    assert _params_for(schemas, "mcp_1__search") == _MCP_SCHEMA


def test_builtin_hardcoded_schema_preserved():
    """Built-ins keep their hardcoded _NATIVE_PARAM_SCHEMAS even though the DB stores {}."""
    wired = [{"key": "web_search", "description": "builtin", "input_schema": {}}]
    schemas = _native_tool_schemas(wired, allow_escalation=False)
    params = _params_for(schemas, "web_search")
    assert params.get("required") == ["query"]
    assert "query" in params.get("properties", {})


def test_empty_schema_falls_back_to_permissive():
    """A tool with genuinely no schema (empty dict) degrades to the permissive fallback."""
    wired = [{"key": "mcp_1__noargs", "description": "no args", "input_schema": {}}]
    schemas = _native_tool_schemas(wired, allow_escalation=False)
    assert _params_for(schemas, "mcp_1__noargs").get("additionalProperties") is True


def test_json_string_schema_parsed_defensively():
    """If a schema is stored as a JSON string it is parsed; garbage degrades to permissive."""
    import json
    good = [{"key": "mcp_1__s", "description": "d", "input_schema": json.dumps(_MCP_SCHEMA)}]
    assert _params_for(_native_tool_schemas(good, allow_escalation=False), "mcp_1__s") == _MCP_SCHEMA

    bad = [{"key": "mcp_1__b", "description": "d", "input_schema": "{not json"}]
    assert _params_for(_native_tool_schemas(bad, allow_escalation=False), "mcp_1__b").get(
        "additionalProperties") is True

    none = [{"key": "mcp_1__n", "description": "d", "input_schema": None}]
    assert _params_for(_native_tool_schemas(none, allow_escalation=False), "mcp_1__n").get(
        "additionalProperties") is True


@pytest_asyncio.fixture
async def host_maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'host.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(MCPServer(id=1, label="docs", command="x", args=[], env=None, status="connected"))
        s.add(Toolset(key="mcp_1", name="docs", description="d", tier="orchestrator", status="registered"))
        s.add(Tool(key="mcp_1__search", toolset_key="mcp_1", description="search docs",
                   tier="orchestrator", status="wired", input_schema=_MCP_SCHEMA,
                   external_name="search", host_enabled=True))
        await s.commit()
    return m


async def test_arslan_host_mcp_tool_schema_reaches_model(host_maker):
    """Arslan's host MCP tools must carry input_schema through `_arslan_tools` so it
    survives the `_native_tool_schemas` conversion in run_native."""
    from server.orchestrator.arslan import _arslan_tools

    tools = await _arslan_tools()
    schemas = _native_tool_schemas(tools, allow_escalation=False)
    assert _params_for(schemas, "mcp_1__search") == _MCP_SCHEMA
