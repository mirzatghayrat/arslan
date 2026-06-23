"""Equip a spawn from the safe-only menu: deterministic shortlist + one LLM pick.

Layer-1 invisibility: the curation prompt is built EXCLUSIVELY from
registry_service.safe_menu(); orchestrator-tier items never enter the prompt.
Layer-2: every returned key still passes assert_assignable before use.
"""
from __future__ import annotations

import logging

from server.orchestrator.json_protocol import parse_json_object
from server.registry import service as registry_service
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

_FALLBACK_TOOLSETS = ["web_search_scraping"]  # core "work smart" capability
_MAX_TOOLSETS = 4
_MAX_SKILLS = 3

_SYSTEM = (
    "You equip a new AI specialist 'spawn' with capabilities. From the MENU below, "
    "pick the few items that best serve the described need. Reply with ONE JSON object "
    'and nothing else: {"toolsets": ["<keys>"], "skills": ["<keys>"], "why": "<one line>"}\n'
    f"- At most {_MAX_TOOLSETS} toolsets and {_MAX_SKILLS} skills. These are CEILINGS, not "
    "targets — pick the MINIMUM the need truly requires.\n"
    "- Relevance only: include an item ONLY if it is DIRECTLY useful for THIS specific need. "
    "If a skill is not clearly relevant, OMIT it. An empty skills list is correct and far "
    "better than padding with an unrelated skill. Never pick an item just to fill a slot.\n"
    "- Only keys that appear in the menu. Items marked (coming soon) may be picked when "
    "clearly core to the role; prefer live items.\n"
    "- Web research (web_search_scraping) fits most research/content roles."
)


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="draft")


def _menu_text(menu: dict) -> str:
    lines = ["TOOLSETS:"]
    for t in menu["toolsets"]:
        live = "live" if t["status"] == "wired" else "coming soon"
        lines.append(f"- {t['key']} ({live}): {t['name']} — {t['description']}")
    lines.append("SKILLS:")
    for s in menu["skills"]:
        lines.append(f"- {s['key']} [{s.get('category', '')}]: {s['description']}")
    return "\n".join(lines)


async def curate(need_description: str) -> dict:
    """Return {"toolsets": [keys], "skills": [keys]} — validated safe-subset only."""
    menu = await registry_service.safe_menu()
    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter
    try:
        resp = await a.chat(
            system=_SYSTEM,
            user=f"Need:\n{need_description}\n\nMENU:\n{_menu_text(menu)}",
        )
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("equipment curate: LLM call failed, using fallback: %s", exc)
        parsed = {}

    toolsets: list[str] = []
    for key in (parsed.get("toolsets") or []):
        try:
            await registry_service.assert_assignable("toolset", str(key))
            toolsets.append(str(key))
            if len(toolsets) >= _MAX_TOOLSETS:
                break
        except registry_service.NotAssignableError:
            logger.warning("equipment curate: dropped non-assignable toolset %r", key)
            continue
    skills: list[str] = []
    for key in (parsed.get("skills") or []):
        try:
            await registry_service.assert_assignable("skill", str(key))
            skills.append(str(key))
            if len(skills) >= _MAX_SKILLS:
                break
        except registry_service.NotAssignableError:
            logger.warning("equipment curate: dropped non-assignable skill %r", key)
            continue

    if not toolsets:
        toolsets = list(_FALLBACK_TOOLSETS)
    return {"toolsets": toolsets, "skills": skills}


async def build_intro(*, name: str, persona_role: str | None, equipment: dict) -> str:
    """Deterministic self-introduction grounded in equipment rows — tags and
    intro can never disagree because both come from the same data."""
    parts = [f"我是 {name}。" + (f"{persona_role}。" if persona_role else "")]
    live = [t["name"] for t in equipment.get("toolsets", []) if t.get("status") == "wired"]
    soon = [t["name"] for t in equipment.get("toolsets", []) if t.get("status") != "wired"]
    skills = [s["name"] for s in equipment.get("skills", [])]
    if live:
        parts.append("我可以实时使用：" + "、".join(live) + "。")
    if soon:
        parts.append("即将接通：" + "、".join(soon) + "。")
    if skills:
        parts.append("我的技法包：" + "、".join(skills) + "。")
    parts.append("需要我做什么，直接说就行。")
    return " ".join(parts)
