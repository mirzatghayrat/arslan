"""Optimizer: propose an improved system_prompt for a spawn from replay evidence.

One LLM call. On any failure or empty output, returns the ORIGINAL prompt (a no-op
candidate), so the evaluator will find no improvement and the gate will not promote.
"""
from __future__ import annotations

import logging

from server.services.llm_factory import build_adapter
from server.services.prompts.optimizer import OPTIMIZER_SYSTEM, build_prompt

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
