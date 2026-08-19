"""LLM: a plain-language intro for non-programmers (user ask 2026-08-20).

Produces {what, use_cases} — one jargon-free sentence and 2-3 everyday
scenarios — so the dossier can tell a normal person what a project is and who
it is for. Conservative like mcp_suggest: any error/unparseable → an empty
shape the UI hides. ADVISORY prose only, nothing executable.
"""
from __future__ import annotations

import logging

from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.repo_overview import REPO_OVERVIEW_SYSTEM

logger = logging.getLogger(__name__)

_EMPTY = {"what": "", "use_cases": []}
_MAX_USE_CASES = 3


async def explain(repo_meta: dict, readme: str) -> dict:
    user = (
        f"Repo: {repo_meta.get('full_name')}\n"
        f"Description: {repo_meta.get('description') or ''}\n"
        f"Topics: {', '.join(repo_meta.get('topics') or [])}\n\n"
        f"README (truncated):\n{(readme or '')[:8000]}"
    )
    try:
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=REPO_OVERVIEW_SYSTEM, user=user)
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("repo_overview failed (defaulting empty): %s", exc)
        return dict(_EMPTY)
    what = parsed.get("what")
    cases = parsed.get("use_cases")
    if not isinstance(what, str) or not isinstance(cases, list):
        return dict(_EMPTY)
    clean = [c for c in cases if isinstance(c, str) and c.strip()][:_MAX_USE_CASES]
    return {"what": what[:300], "use_cases": clean}
