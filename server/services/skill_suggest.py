"""LLM: distill a GitHub repo into a SKILL.md technique body. Conservative — any error /
unparseable / missing required sections → None. Output is ADVISORY (user reviews + edits)."""
from __future__ import annotations

import logging

from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.skill_suggest import SKILL_SUGGEST_SYSTEM

logger = logging.getLogger(__name__)

_REQUIRED = ("## Trigger", "## 决策规则")


def has_required_sections(body: str) -> bool:
    b = body or ""
    return all(sec in b for sec in _REQUIRED)


async def generate_skill(repo_meta: dict, readme: str) -> dict | None:
    user = (
        f"Repo: {repo_meta.get('full_name')}\n"
        f"Description: {repo_meta.get('description') or ''}\n"
        f"Topics: {', '.join(repo_meta.get('topics') or [])}\n\n"
        f"README (truncated):\n{(readme or '')[:8000]}"
    )
    try:
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=SKILL_SUGGEST_SYSTEM, user=user)
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill_suggest failed: %s", exc)
        return None
    body = parsed.get("body")
    name = parsed.get("name")
    if not isinstance(body, str) or not isinstance(name, str) or not name.strip():
        return None
    if not has_required_sections(body):
        return None
    return {
        "name": name.strip()[:100],
        "category": str(parsed.get("category") or "general")[:40],
        "description": str(parsed.get("description") or "")[:300],
        "body": body,
    }
