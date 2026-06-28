"""Sandbox-session helpers: one-line TL;DR for the merged deliverable."""
from __future__ import annotations

import logging

from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = "用一句话(≤20字)概括下面这条最终产出,只输出这句话,不要前缀、不要引号。"


async def summarize_deliverable(spawn_name: str, content: str) -> str:
    """Return a ≤20-char TL;DR of the deliverable. Falls back to its first line on any
    LLM failure; empty content yields empty string. Never raises."""
    text = (content or "").strip()
    if not text:
        return ""
    try:
        adapter = await build_adapter(role="worker")
        resp = await adapter.chat(system=_SUMMARY_SYSTEM, user=text[:4000])
        line = (resp.content or "").strip().splitlines()[0].strip() if resp.content else ""
        if line:
            return line[:40]
    except Exception as exc:  # noqa: BLE001
        logger.warning("summarize_deliverable fell back to first line: %s", exc)
    return text.splitlines()[0].strip()[:40]
