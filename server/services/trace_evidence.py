"""Shared step-evidence builder for judge prompts (E1).

Renders a Run's recorded RunStep rows as one compact line per step so the judge
(single-run AND paired) sees what ACTUALLY happened — the ground truth against
which claimed deliverables are diffed for the fabrication dimension:

    [kind] tool=<name> args=<args_summary> → ok|err <result summary>

Discipline: each line ≤ STEP_CAP chars, whole block ≤ TOTAL_CAP chars (a cut
appends TRUNC_MARK). A run with no steps yields "" — evidence is never
fabricated. Malformed step payloads (ref/detail not dicts, weird value types)
are skipped defensively; this builder must never raise.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import RunStep

logger = logging.getLogger(__name__)

STEP_CAP = 200     # max chars per rendered step line
TOTAL_CAP = 2000   # max chars for the whole evidence block
TRUNC_MARK = "…[truncated]"


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - len(TRUNC_MARK)] + TRUNC_MARK


def _render_step(step: RunStep) -> str | None:
    """One evidence line for one step, or None if the step is unusable."""
    ref = _as_dict(step.ref)
    detail = _as_dict(step.detail)
    kind = str(step.kind or "step")
    tool = str(ref.get("tool") or ref.get("spawn_name") or "-")
    args = str(detail.get("args_summary") or "")
    ok = ref.get("ok")
    status = "err" if ok is False else "ok"
    if ok is False:
        result = str(detail.get("error") or detail.get("summary") or "")
    else:
        result = str(detail.get("summary") or detail.get("output_preview") or "")
    line = f"[{kind}] tool={tool} args={args} → {status} {result}".rstrip()
    return _cap(line, STEP_CAP)


async def build_evidence(run_id: int) -> str:
    """Compact step-evidence block for one Run ('' when there are no steps)."""
    async with db_session.AsyncSessionLocal() as db:
        steps = (await db.execute(
            select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq)
        )).scalars().all()
    lines: list[str] = []
    total = 0
    for step in steps:
        try:
            line = _render_step(step)
        except Exception:  # noqa: BLE001 — a bad step must never break judging
            logger.warning("trace_evidence: skipping malformed step in run %s", run_id)
            continue
        if line is None:
            continue
        # +1 for the joining newline; keep room for a final TRUNC_MARK.
        if total + len(line) + (1 if lines else 0) > TOTAL_CAP - len(TRUNC_MARK):
            lines.append(TRUNC_MARK)
            break
        total += len(line) + (1 if lines else 0)
        lines.append(line)
    return "\n".join(lines)
