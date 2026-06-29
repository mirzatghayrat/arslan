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
