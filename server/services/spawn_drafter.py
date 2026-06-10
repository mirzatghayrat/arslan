"""Infer a spawn draft from a natural-language description (shared by manual create + Tweak refine)."""
from __future__ import annotations

import json
from typing import Any

from server.orchestrator import memory
from server.orchestrator import router as _router  # used only for _spawn_registry
from server.orchestrator.json_protocol import parse_json_object
from server.services import spawn_service
from server.services.llm_factory import build_adapter

_SYSTEM = (
    "You design AI specialist 'spawns' from a natural-language description. "
    "Reply with ONE JSON object and nothing else:\n"
    '{"name": "<short-kebab-name>", "domain": "<free-form category.subcategory you infer, '
    'e.g. finance.equity-research>", "capabilities": ["..."], "persona_role": "...", '
    '"persona_tone": "...", "reason": "<one line>"}\n'
    "Infer a specific, fine-grained domain string from the description — do NOT force it into "
    "a small fixed set of categories."
)


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter()


def _parse(content: str) -> dict[str, Any]:
    return parse_json_object(content or "") or {}


async def draft_from_text(description: str, *, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a draft dict {name, domain, capabilities, persona_role, persona_tone, reason}.
    When `previous` is given, this is a refinement: revise that draft per the description."""
    registry = await _router._spawn_registry()
    facts = await memory.facts_text()
    parts = [f"Existing spawns:\n{registry}"]
    if facts:
        parts.append(facts)
    if previous:
        parts.append("Refine THIS existing draft per the instruction below:\n" + json.dumps(previous, ensure_ascii=False))
    parts.append(f"Description / instruction:\n{description}")
    prompt = "\n\n".join(parts)

    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter
    resp = await a.chat(system=_SYSTEM, user=prompt)
    draft = _parse(resp.content)
    draft.setdefault("name", "new-spawn")
    draft.setdefault("domain", "other")
    # Coerce capabilities to a clean list (the model may return a comma-joined string).
    draft["capabilities"] = spawn_service.normalize_capabilities(draft.get("capabilities"))
    return draft
