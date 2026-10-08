"""Arslan adapts a drafted plan to the project (0.1.56 §3.2).

One model call, on the user's own model, when the user asks for it ("让 Arslan 细化"): the
template draft (or what the user already edited) plus the finish line and the user's
enabled plan rules go in; the same levels come back with descriptions, observable clear
conditions and a few checkable checkpoints. Nothing is saved here — the result goes back
to the editor, and only the user's "Create" saves it. Any failure keeps the draft as it was.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import or_, select

from server.db import session as db_session
from server.db.models import ProjectHabit
from server.orchestrator.json_protocol import parse_json_object
from server.services import project_templates
from server.services.llm_factory import build_adapter
from server.services.project_plan import PlanError, _clean_level

logger = logging.getLogger(__name__)

LANGUAGE_NAMES = {"en": "English", "zh": "Simplified Chinese", "ja": "Japanese", "es": "Spanish", "de": "German",
                  "fr": "French"}
BAND_ORDER = {"shaping": 0, "doing": 1, "done": 2}

_SYSTEM = (
    "You adapt a project's plan of levels to what the project must become. Reply with ONE JSON object only:\n"
    '{"levels": [{"name": str, "band": "shaping"|"doing"|"done", "description": str, "clear_condition": str, '
    '"habit": bool, "checkpoints": [{"text": str, "expects": {"kind": "file", "pattern": str} | null}]}]}\n'
    "Rules:\n"
    "- Keep the given levels and their order unless the finish line clearly needs a level more or less; "
    "3 to 12 levels; bands never go backwards (shaping, then doing, then done); the last level is done.\n"
    "- description: one short line. clear_condition: something a person can see is true, never vague.\n"
    "- 0 to 5 checkpoints per level, each concrete. Only when a checkpoint obviously produces a file in the "
    "project folder, add expects with a relative glob (e.g. \"levels/*.json\"); otherwise null.\n"
    "- A level added because of one of the user's plan rules gets habit: true.\n"
    "- Write every text in {language}. Never invent facts about the user."
)


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="draft")


async def plan_rules(template: str, owner_id: str = "local") -> list[str]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(ProjectHabit.text).where(
            ProjectHabit.owner_id == owner_id, ProjectHabit.kind == "plan_rule", ProjectHabit.enabled.is_(True),
            or_(ProjectHabit.template == template, ProjectHabit.template.is_(None)),
        ).order_by(ProjectHabit.created_at))).scalars().all()
    return list(rows)[:10]


def _valid(levels: list) -> list[dict] | None:
    if not isinstance(levels, list) or not 3 <= len(levels) <= 12:
        return None
    try:
        clean = [_clean_level(raw if isinstance(raw, dict) else {}) for raw in levels]
    except PlanError:
        return None
    order = [BAND_ORDER[lv["band"]] for lv in clean]
    if order != sorted(order) or clean[-1]["band"] != "done":
        return None
    for lv in clean:
        lv.pop("id", None)
        lv["checkpoints"] = [{"text": cp["text"], "expects": cp["expects"]} for cp in lv["checkpoints"][:5]]
    return clean


async def refine(template: str, finish_line: str, lang: str | None, levels: list[dict]) -> list[dict] | None:
    """The model's version of the plan, validated; None when there is no model, the call
    fails, or what comes back does not hold the rules (the caller keeps the draft)."""
    language = project_templates.lang_of(lang)
    rules = await plan_rules(template)
    prompt = json.dumps({"type": template, "finish_line": finish_line, "levels": levels, "plan_rules": rules},
                        ensure_ascii=False)
    try:
        from server.services import usage_ledger
        async with usage_ledger.scope("projects_draft", None):
            adapter = _get_adapter()
            a = await adapter if hasattr(adapter, "__await__") else adapter
            response = await a.chat(system=_SYSTEM.replace("{language}", LANGUAGE_NAMES[language]), user=prompt)
        parsed = parse_json_object(response.content or "")
    except Exception as exc:  # noqa: BLE001 — no model, network, or a bad reply: keep the draft
        logger.warning("project drafter failed: %s", exc)
        return None
    if not isinstance(parsed, dict):
        return None
    return _valid(parsed.get("levels"))
