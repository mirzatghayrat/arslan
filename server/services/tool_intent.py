"""LLM judgment: does the task need a tool first, and which one (with a query)?

Conservative: any error/unparseable/uncertain → needs=False."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter, build_conversation_adapter
from server.services.prompts.tool_intent import TOOL_INTENT_SYSTEM

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolIntent:
    needs: bool
    tool: str | None
    query: str | None


async def _conversation_adapter(conversation_id: str | None):
    """The conversation's own model, or None (no choice, or one that can't be built: the primary then)."""
    try:
        return await build_conversation_adapter(conversation_id)
    except Exception:  # noqa: BLE001 — a broken choice must not take the check down
        return None


async def classify(task: str, available_tool_keys: list[str], conversation_id: str | None = None) -> ToolIntent:
    """Whether the task needs a tool first. Runs on the conversation's own model, else the primary (v0.1.64 ROUTE1)."""
    user = f"Task: {task}\nAvailable tools: {', '.join(available_tool_keys) or '(none)'}"
    try:
        adapter = await _conversation_adapter(conversation_id) or await build_adapter(role="judgment")
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
