"""Gather the 4 staffing slots across turns: LLM-nullable extraction + deterministic readiness."""
from __future__ import annotations

import logging

from server.orchestrator.json_protocol import parse_json_object
from server.orchestrator.untrusted import wrap_external
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

SLOTS = ("domain", "capability", "first_task", "recurrence")

_SYSTEM = (
    "Extract staffing requirements as JSON with EXACTLY these keys: "
    "domain (english 'category.subcategory' of the need, or null if not yet clear), "
    "capability (one concrete capability phrase, or null), "
    "first_task (a concrete first task to run, or null), "
    "recurrence (true if the user signalled this is a recurring/ongoing need worth a "
    "dedicated agent; false if the user signalled this is a one-off/just-this-once task; "
    "null only if it is not yet clear whether the need is recurring or one-off). "
    "Use null for the OTHER keys when not yet confidently present — do NOT guess."
)


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="draft")


def merge_slots(old: dict, new: dict) -> dict:
    """Merge new slots into old, never overwriting a filled slot with null."""
    out = dict(old or {})
    for k in SLOTS:
        out.setdefault(k, None)
        v = (new or {}).get(k)
        if v is not None and out.get(k) is None:
            out[k] = v
    return out


def is_ready(slots: dict) -> bool:
    """Return True only when all 4 slots are non-null."""
    return all((slots or {}).get(k) is not None for k in SLOTS)


def missing_slots(slots: dict) -> list[str]:
    """Return the list of slot names that are still null."""
    return [k for k in SLOTS if (slots or {}).get(k) is None]


async def extract_slots(history_text: str) -> dict:
    """One LLM call → nullable slot dict. Best-effort: returns all-null on failure."""
    try:
        adapter = _get_adapter()
        adapter = await adapter if hasattr(adapter, "__await__") else adapter
        resp = await adapter.chat(system=_SYSTEM, user=wrap_external(history_text))
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("gather: extract failed: %s", exc)
        parsed = {}
    return {k: (parsed.get(k) if parsed.get(k) not in ("", []) else None) for k in SLOTS}


# System prompt is STATIC on purpose (prompt-cache discipline — all dynamic content,
# including the registry domain lists, goes in the user turn; see the router's
# build_cached_system precedent). The "small edit to work already in progress" clause
# exists because the BUG1 incident's real shape was an in-context tweak the host should
# simply do — that shape must resolve to null, not to a domain guess.
_DOMAIN_CONFLICT_SYSTEM = (
    "You check whether a task was routed to the WRONG domain specialist. The user "
    "message names the ASSIGNED specialist's domain, the OTHER available domains, and "
    "the task. Return JSON {\"domain\": \"<one of the OTHER domains>\"} ONLY when the "
    "task clearly does NOT belong to the assigned domain AND clearly belongs to that "
    "other domain. In every other case — the task plausibly fits the assigned domain, "
    "no listed domain clearly fits, you are unsure, or the task is a small "
    "edit/adjustment to work already in progress in this conversation — return "
    "{\"domain\": null}. Do NOT guess."
)


async def extract_conflicting_domain(
    task_text: str, pick_domain: str, other_domains: list[str]
) -> str | None:
    """One LLM call → a clearly-better OTHER registry domain for the task, else None.

    Registry-anchored and pick-referenced (the BUG1 cell-6 gate): the model may only
    answer from ``other_domains``; the pick's own domain, an off-list string, null, or
    ANY failure all yield None. Callers treat None as "no affirmative contradiction"
    (the recruit chip floats — PA-2 keeps that chip band-independent)."""
    try:
        adapter = _get_adapter()
        adapter = await adapter if hasattr(adapter, "__await__") else adapter
        user = (
            f"ASSIGNED domain: {pick_domain}\n"
            f"OTHER available domains: {', '.join(other_domains)}\n\n"
            f"TASK:\n{wrap_external(task_text)}"
        )
        resp = await adapter.chat(system=_DOMAIN_CONFLICT_SYSTEM, user=user)
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("gather: domain-conflict extract failed: %s", exc)
        return None
    domain = parsed.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        return None
    domain = domain.strip()
    return domain if domain in other_domains else None
