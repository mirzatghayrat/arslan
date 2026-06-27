"""LLM: classify a GitHub repo as an MCP server + suggest a run command. Conservative —
any error / unparseable / unknown transport → is_mcp=False. Output is ADVISORY (user confirms)."""
from __future__ import annotations

import logging

from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.mcp_suggest import MCP_SUGGEST_SYSTEM

logger = logging.getLogger(__name__)

_SAFE = {"is_mcp": False, "transport": None, "command": None, "args": [], "url": None, "reason": "无法确定"}


async def classify_and_suggest(repo_meta: dict, readme: str) -> dict:
    user = (
        f"Repo: {repo_meta.get('full_name')}\n"
        f"Description: {repo_meta.get('description') or ''}\n"
        f"Topics: {', '.join(repo_meta.get('topics') or [])}\n\n"
        f"README (truncated):\n{(readme or '')[:8000]}"
    )
    try:
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=MCP_SUGGEST_SYSTEM, user=user)
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_suggest failed (defaulting is_mcp=False): %s", exc)
        return dict(_SAFE)
    if not parsed.get("is_mcp"):
        return dict(_SAFE)
    transport = parsed.get("transport")
    if transport not in ("stdio", "http"):
        return dict(_SAFE)
    args = parsed.get("args")
    return {
        "is_mcp": True,
        "transport": transport,
        "command": (parsed.get("command") or None),
        "args": args if isinstance(args, list) else [],
        "url": (parsed.get("url") or None),
        "reason": str(parsed.get("reason") or "")[:300],
    }
