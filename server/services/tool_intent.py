"""LLM judgment: does the task need a tool first, and which one (with a query)?

Same conservative pattern as storage_intent — any error/unparseable/uncertain → needs=False."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.tool_intent import TOOL_INTENT_SYSTEM

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolIntent:
    needs: bool
    tool: str | None
    query: str | None


async def classify(task: str, available_tool_keys: list[str]) -> ToolIntent:
    user = f"Task: {task}\nAvailable tools: {', '.join(available_tool_keys) or '(none)'}"
    try:
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=TOOL_INTENT_SYSTEM, user=user)
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool_intent classify failed (defaulting to needs=False): %s", exc)
        return ToolIntent(needs=False, tool=None, query=None)
    needs = bool(parsed.get("needs"))
    tool = parsed.get("tool")
    if not isinstance(tool, str) or tool not in available_tool_keys:
        tool = None                       # unknown / unavailable tool → drop
    query = parsed.get("query")
    if not isinstance(query, str) or not query.strip():
        query = None
    return ToolIntent(needs=needs and tool is not None, tool=tool, query=query)
