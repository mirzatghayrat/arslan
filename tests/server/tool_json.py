"""The size of the tool table one request sends (C3; K7's ≤ 12k check uses the same function).

It is the table run_native hands the model adapter (`tool_loop._native_tool_schemas`), as JSON without
ASCII escapes, in characters. The host paths send it with `allow_escalation=False`.
"""
import json

from server.orchestrator import tool_loop


def rendered_tool_json_chars(wired: list[dict], *, allow_escalation: bool = False) -> int:
    schemas = tool_loop._native_tool_schemas(wired, allow_escalation=allow_escalation)
    return len(json.dumps(schemas, ensure_ascii=False))
