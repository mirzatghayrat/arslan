"""K5: every built-in tool the model is offered has a parameter schema (card K5, ⓪Plan's Q9).

Before, 14 offered tools had none and fell back to an empty "anything goes" schema. That's the card's 11
plus scan_local_network, ssh_run and list_nodes.

Built-in schemas go to every provider verbatim (F3's normaliser in arslan/llm/tool_schema.py handles only
MCP tools), so they keep to what every provider accepts:
- no `pattern` (DeepSeek refuses it);
- no top-level `anyOf` (Anthropic refuses it);
- no type arrays (providers accept different subsets).
"""
import pytest

from server.orchestrator import tool_loop
from server.registry.executors import EXECUTORS

SCHEMAS = tool_loop._NATIVE_PARAM_SCHEMAS
NEW = ("edit_file", "list_dir", "search_files", "whats_new", "list_my_capabilities", "schedule_task",
       "list_my_tasks", "cancel_task", "read_skill", "scan_local_network", "ssh_probe", "ssh_run", "list_nodes",
       "enroll_node")


def _offered():
    return sorted(k for k in set(EXECUTORS) | {"update_plan", "ask_user_choice"} if not k.startswith("mcp_"))


def test_every_offered_builtin_tool_has_a_schema():
    assert [k for k in _offered() if k not in SCHEMAS] == []


@pytest.mark.parametrize("key", NEW)
def test_each_new_schema_names_its_arguments_or_takes_none(key):
    schema = SCHEMAS[key]
    assert schema.get("type") == "object"
    assert schema.get("properties") or schema.get("additionalProperties") is False


def _walk(node, path, out):
    if isinstance(node, dict):
        if "pattern" in node:
            out.append(f"{path}: pattern")
        if isinstance(node.get("type"), list):
            out.append(f"{path}: type array")
        for k, v in node.items():
            _walk(v, f"{path}.{k}", out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(v, f"{path}[{i}]", out)


def test_no_schema_uses_what_a_provider_refuses():
    bad = []
    for key, schema in SCHEMAS.items():
        if "anyOf" in schema:
            bad.append(f"{key}: top-level anyOf")
        _walk(schema, key, bad)
    assert bad == []


@pytest.mark.parametrize("task_id", [3, "3"])
def test_a_task_id_as_a_number_or_a_string_still_passes_the_check_before_dispatch(task_id):
    assert tool_loop._schema_problem({"task_id": task_id}, SCHEMAS["cancel_task"]) is None


def test_schemas_match_the_executors_required_arguments():
    for key, required in {"search_files": ["query"], "schedule_task": ["name", "prompt", "when"],
                          "cancel_task": ["task_id"], "read_skill": ["key"], "ssh_probe": ["host"],
                          "ssh_run": ["host", "user", "command"], "enroll_node": ["host", "user", "name"],
                          "edit_file": ["path", "old_string", "new_string"]}.items():
        assert sorted(SCHEMAS[key].get("required", [])) == sorted(required), key
    assert "conversation_id" not in SCHEMAS["schedule_task"]["properties"]      # read, never advertised
