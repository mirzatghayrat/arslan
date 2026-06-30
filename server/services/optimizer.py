"""Optimizer: propose an improved system_prompt for a spawn from replay evidence.

One LLM call. On any failure or empty output, returns the ORIGINAL prompt (a no-op
candidate), so the evaluator will find no improvement and the gate will not promote.
"""
from __future__ import annotations

import logging

from server.orchestrator.json_protocol import parse_json_object
from server.orchestrator.untrusted import wrap_external
from server.services.llm_factory import build_adapter
from server.services.prompts.optimizer import (
    OPTIMIZER_EDIT_SYSTEM,
    OPTIMIZER_SYSTEM,
    build_edit_prompt,
    build_prompt,
)

logger = logging.getLogger(__name__)


def _evidence_digest(replay_items: list[dict]) -> str:
    lines = []
    for it in replay_items:
        dims = it.get("baseline_dims") or {}
        dim_str = ", ".join(
            f"{d}={v.get('score')}({v.get('status')})" for d, v in dims.items()
        )
        lines.append(f"- task: {it.get('task', '')[:200]}\n  overall={it.get('baseline_overall')} dims: {dim_str}")
    return "\n".join(lines)


def _evidence_digest_edits(train_items: list[dict]) -> str:
    lines = []
    for it in train_items:
        dims = it.get("baseline_dims") or {}
        dim_str = ", ".join(
            f"{d}={v.get('score')}({v.get('status')})" for d, v in dims.items()
        )
        lines.append(
            f"- task: {str(it.get('task', ''))[:200]}\n  overall={it.get('baseline_overall')} dims: {dim_str}"
        )
    return "\n".join(lines)


def _same_edit(a: dict, b: dict) -> bool:
    return (
        a.get("op") == b.get("op")
        and a.get("section") == b.get("section")
        and a.get("content", "") == b.get("content", "")
    )


async def propose_edits(
    spawn,
    train_items: list[dict],
    *,
    lr_budget: int,
    avoid: list[dict],
) -> list[dict]:
    """One LLM call -> a list of <= lr_budget bounded section edits, excluding the
    rejected-edit buffer. On any failure/empty -> [] (a no-op round). Train evidence
    (spawn-derived text) is wrapped with untrusted.wrap_external."""
    try:
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(
            system=OPTIMIZER_EDIT_SYSTEM,
            user=build_edit_prompt(
                name=spawn.name,
                persona_role=spawn.persona_role or "",
                persona_tone=spawn.persona_tone or "",
                current_doc=spawn.system_prompt or "",
                evidence=wrap_external(_evidence_digest_edits(train_items)),
                lr_budget=lr_budget,
            ),
        )
        parsed = parse_json_object(resp.content or "") or {}
        raw = parsed.get("edits") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("optimizer.propose_edits failed, no edits: %s", exc)
        return []

    edits: list[dict] = []
    for e in raw:
        if not isinstance(e, dict) or e.get("op") not in ("add", "delete", "replace"):
            continue
        if any(_same_edit(e, a) for a in (avoid or [])):
            continue
        edits.append(
            {"op": e["op"], "section": e.get("section", ""), "content": e.get("content", "")}
        )
        if len(edits) >= lr_budget:
            break
    return edits


async def propose(spawn, replay_items: list[dict]) -> str:
    """Return a candidate system_prompt; falls back to the original on failure/empty."""
    original = spawn.system_prompt or ""
    try:
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(
            system=OPTIMIZER_SYSTEM,
            user=build_prompt(
                name=spawn.name,
                persona_role=spawn.persona_role or "",
                persona_tone=spawn.persona_tone or "",
                current_prompt=original,
                evidence=_evidence_digest(replay_items),
            ),
        )
        candidate = (resp.content or "").strip()
        return candidate if candidate else original
    except Exception as exc:  # noqa: BLE001
        logger.warning("optimizer.propose failed, returning original: %s", exc)
        return original
