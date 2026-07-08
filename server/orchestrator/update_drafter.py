"""Conversational spawn-update drafter (P2).

Mirrors the suggest_create pattern: the router flags an UPDATE intent, this module drafts a
structured change-set from the user's words, and the spine emits a `suggest_update` frame.
NOTHING is applied here — the user's `confirm_update` (ws/arslan.py) is the only apply path,
and equipment changes still pass the Layer-2 choke (assert_assignable) there.

The equipment menus given to the LLM come from safe_menu() — post-P0 that menu is honest
(functional-only), so the drafter cannot propose catalog-only decoration.
"""
from __future__ import annotations

import logging
from typing import Any

from server.db import session as db_session
from server.db.models import Spawn
from server.orchestrator.json_protocol import parse_json_object
from server.registry import service as registry_service
from server.services import persona_lint
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

_CHANGE_KEYS = ("persona_role", "persona_tone", "capabilities",
                "add_toolsets", "remove_toolsets", "add_skills", "remove_skills")

_SYSTEM = (
    "You edit an EXISTING specialist agent per the user's request. Reply ONE JSON object only:\n"
    '{"persona_role": "<full replacement text>" | null, "persona_tone": "<text>" | null, '
    '"capabilities": ["<tag>", ...] | null, "add_toolsets": [], "remove_toolsets": [], '
    '"add_skills": [], "remove_skills": [], "reason": "<short, user\'s language>"}\n'
    "Rules:\n"
    "- Change ONLY what the user asked for; set everything else to null / [].\n"
    "- persona_role must stay a COMPLETE role description — edit the current text, never truncate it.\n"
    "- add_* keys MUST come from the AVAILABLE menus; remove_* keys MUST come from the EQUIPPED lists.\n"
    "- If the request maps to nothing editable here, return all nulls/empties with a reason."
)


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="draft")


async def draft_update(spawn_id: int, request_text: str) -> dict[str, Any] | None:
    """Draft a validated change-set for `spawn_id` from the user's request.

    Returns {spawn_id, spawn_name, current, changes, reason} for the suggest_update frame,
    or None when the spawn is missing / the LLM fails / no valid change survives filtering
    (the caller falls back to a plain answer)."""
    async with db_session.AsyncSessionLocal() as db:
        spawn = await db.get(Spawn, spawn_id)
    if spawn is None:
        return None

    equipment = await registry_service.equipment_for_spawn(spawn_id)
    menu = await registry_service.safe_menu()
    equipped_ts = [t["key"] for t in equipment["toolsets"]]
    equipped_sk = [s["key"] for s in equipment["skills"]]

    current = {
        "persona_role": spawn.persona_role or "",
        "persona_tone": spawn.persona_tone or "",
        "capabilities": list(spawn.capabilities or []),
        "toolsets": equipped_ts,
        "skills": equipped_sk,
    }
    prompt = (
        f"Agent: {spawn.name}\n"
        f"Current persona_role: {current['persona_role']}\n"
        f"Current persona_tone: {current['persona_tone']}\n"
        f"Current capabilities: {', '.join(current['capabilities']) or '(none)'}\n"
        f"EQUIPPED toolsets: {', '.join(equipped_ts) or '(none)'}\n"
        f"EQUIPPED skills: {', '.join(equipped_sk) or '(none)'}\n"
        f"AVAILABLE toolsets: {', '.join(t['key'] for t in menu['toolsets'])}\n"
        f"AVAILABLE skills: {', '.join(s['key'] for s in menu['skills'])}\n\n"
        f"User's change request:\n{request_text}"
    )
    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter
    try:
        resp = await a.chat(system=_SYSTEM, user=prompt)
        parsed = parse_json_object(resp.content or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("update drafter LLM failed: %s", exc)
        return None
    if not isinstance(parsed, dict):
        return None

    menu_ts = {t["key"] for t in menu["toolsets"]}
    menu_sk = {s["key"] for s in menu["skills"]}
    changes: dict[str, Any] = {}
    if isinstance(parsed.get("persona_role"), str) and parsed["persona_role"].strip():
        changes["persona_role"] = parsed["persona_role"].strip()
    if isinstance(parsed.get("persona_tone"), str) and parsed["persona_tone"].strip():
        changes["persona_tone"] = parsed["persona_tone"].strip()
    if isinstance(parsed.get("capabilities"), list):
        caps = [str(c).strip() for c in parsed["capabilities"] if str(c).strip()]
        if caps and caps != current["capabilities"]:
            changes["capabilities"] = caps
    # adds must be in the honest menu AND not already equipped; removes must be equipped.
    def _keys(name: str, allowed: set[str] | list[str]) -> list[str]:
        raw = parsed.get(name)
        if not isinstance(raw, list):
            return []
        return [str(k) for k in raw if str(k) in set(allowed)]
    add_ts = [k for k in _keys("add_toolsets", menu_ts) if k not in equipped_ts]
    add_sk = [k for k in _keys("add_skills", menu_sk) if k not in equipped_sk]
    rm_ts = _keys("remove_toolsets", equipped_ts)
    rm_sk = _keys("remove_skills", equipped_sk)
    for name, val in (("add_toolsets", add_ts), ("remove_toolsets", rm_ts),
                      ("add_skills", add_sk), ("remove_skills", rm_sk)):
        if val:
            changes[name] = val

    if not changes:
        return None

    # HX-6/P2: advisory delivery lint on the PROPOSED persona vs the RESULTING
    # equipment (equipped − removes + adds), so the confirm card can warn when the
    # new persona promises a format the spawn still couldn't deliver. Fail-open.
    persona_text = " ".join(filter(None, [
        changes.get("persona_role") or current["persona_role"],
        changes.get("persona_tone") or current["persona_tone"],
    ]))
    resulting_ts = [k for k in equipped_ts if k not in set(changes.get("remove_toolsets") or [])]
    resulting_ts += [k for k in changes.get("add_toolsets") or [] if k not in resulting_ts]
    try:
        tool_keys = await persona_lint.tool_keys_for_toolsets(resulting_ts)
        capability_warnings = persona_lint.lint_delivery_claims(persona_text, tool_keys)
    except Exception as exc:  # noqa: BLE001 — advisory, never blocks the proposal
        logger.warning("persona lint failed in draft_update: %s", exc)
        capability_warnings = []

    return {"spawn_id": spawn.id, "spawn_name": spawn.name, "current": current,
            "changes": changes, "reason": str(parsed.get("reason") or ""),
            "capability_warnings": capability_warnings}
