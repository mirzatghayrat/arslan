"""Pairwise compare-judge: which of two outputs (A/B) is better, per dimension.

Used by the offline evolution loop to prove a candidate config beats the baseline.
Position bias is mitigated by running A/B in both orders and merging: a dimension
(or overall) has a winner only when BOTH passes agree; any disagreement → tie.
Any parse/LLM failure degrades to an all-tie verdict (safe side: 'not proven better').
"""
from __future__ import annotations

import logging

from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.compare_judge import COMPARE_SYSTEM, build_prompt

logger = logging.getLogger(__name__)

_DIMENSIONS = ("fabrication", "identity", "completion")

_DEGRADED = {
    "dimensions": {d: "tie" for d in _DIMENSIONS},
    "overall": "tie",
    "margin": 0.0,
    "position_sensitive": True,
    "reason": "judge parse/LLM failed",
}


async def _judge_once(adapter, *, task: str, persona: str, first: str, second: str) -> dict | None:
    """One judge pass; 'first'/'second' are shown as 输出① / 输出②.
    Returns the parsed dict (values in "1"/"2"/"tie"), or None on failure."""
    try:
        resp = await adapter.chat(
            system=COMPARE_SYSTEM,
            user=build_prompt(task=task, persona=persona, first=first, second=second),
        )
        parsed = parse_json_object(resp.content or "")
        if not isinstance(parsed, dict) or "dimensions" not in parsed or "overall" not in parsed:
            return None
        return parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("compare _judge_once failed: %s", exc)
        return None


def _slot_to_ab(value: str, *, slot1: str, slot2: str) -> str:
    """Map a judge's "1"/"2"/"tie" to "a"/"b"/"tie". slot1/slot2 say which of A/B
    occupied ①/② in that pass."""
    if value == "1":
        return slot1
    if value == "2":
        return slot2
    return "tie"


def _to_ab(pass_: dict, *, slot1: str, slot2: str) -> tuple[dict, str, float]:
    dims = {
        d: _slot_to_ab(str(pass_["dimensions"].get(d, "tie")), slot1=slot1, slot2=slot2)
        for d in _DIMENSIONS
    }
    overall = _slot_to_ab(str(pass_.get("overall", "tie")), slot1=slot1, slot2=slot2)
    try:
        margin = float(pass_.get("margin", 0) or 0)
    except (TypeError, ValueError):
        margin = 0.0
    return dims, overall, margin


async def compare(*, task: str, persona: str, output_a: str, output_b: str) -> dict:
    """Compare output_a vs output_b. Returns:
      {"dimensions": {dim: "a"|"b"|"tie"}, "overall": "a"|"b"|"tie",
       "margin": float, "position_sensitive": bool, "reason": str}
    """
    adapter = await build_adapter(role="judge")
    p1 = await _judge_once(adapter, task=task, persona=persona, first=output_a, second=output_b)
    p2 = await _judge_once(adapter, task=task, persona=persona, first=output_b, second=output_a)
    if p1 is None or p2 is None:
        return dict(_DEGRADED)

    d1, o1, m1 = _to_ab(p1, slot1="a", slot2="b")   # pass1: ①=A
    d2, o2, m2 = _to_ab(p2, slot1="b", slot2="a")   # pass2: ①=B

    def merge(x: str, y: str) -> str:
        return x if x == y else "tie"

    dims = {d: merge(d1[d], d2[d]) for d in _DIMENSIONS}
    overall = merge(o1, o2)
    position_sensitive = o1 in ("a", "b") and o2 in ("a", "b") and o1 != o2
    margin = round((m1 + m2) / 2, 2) if overall != "tie" else 0.0
    reason = (p1.get("reason") or p2.get("reason") or "")[:300]

    return {
        "dimensions": dims,
        "overall": overall,
        "margin": margin,
        "position_sensitive": position_sensitive,
        "reason": reason,
    }
