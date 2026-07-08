"""Async LLM judge: score a recorded Run on four dimensions, persist the verdict."""
from __future__ import annotations

import logging

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, Run, RunEvaluation, RunStep, Spawn
from server.orchestrator import promise_guard
from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.run_judge import JUDGE_SYSTEM, build_prompt

logger = logging.getLogger(__name__)

_DIMENSIONS = ("routing", "fabrication", "identity", "completion")


async def _roster_text() -> str:
    async with db_session.AsyncSessionLocal() as db:
        spawns = (await db.execute(select(Spawn))).scalars().all()
    if not spawns:
        return "(no spawns)"
    return "\n".join(
        f"- {s.name} ({s.domain_category}"
        + (f".{s.domain_subcategory}" if s.domain_subcategory else "")
        + (f") — {s.persona_role}" if s.persona_role else ")")
        for s in spawns
    )


def _coerce_dim(raw: dict) -> tuple[str, float, str]:
    status = str(raw.get("status", "warn"))
    if status not in ("pass", "warn", "fail"):
        status = "warn"
    try:
        score = float(raw.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    return status, score, str(raw.get("comment", ""))


async def score(run_id: int) -> None:
    """Score a Run. Sets status 'scored' (or 'score_failed' on any error)."""
    async with db_session.AsyncSessionLocal() as db:
        run = await db.get(Run, run_id)
        if run is None:
            return
        spawn = await db.get(Spawn, run.spawn_id) if run.spawn_id else None
        out_row = (await db.execute(
            select(ArslanMessage).where(
                ArslanMessage.run_id == run_id,
                ArslanMessage.role == "spawn_summary",
            )
        )).scalars().first()
        step_kinds = (await db.execute(
            select(RunStep.kind).where(RunStep.run_id == run_id)
        )).scalars().all()
    output = (out_row.display_content or out_row.content) if out_row else ""
    persona = ""
    if spawn is not None:
        persona = f"role: {spawn.persona_role or ''}\ntone: {spawn.persona_tone or ''}\n{spawn.system_prompt or ''}"

    # HX-5 A4 deterministic pre-check: the final output claims in-progress/handed-off
    # work (promise_guard.PROMISE_RE) but the run recorded ZERO tool_call steps — any
    # such promise is structurally suspect (nothing was actually executed). The signal
    # is injected into the judge prompt AND persisted (prefix on the fabrication
    # verdict comment) so the diagnosis UI / future threshold-tuning can see it.
    fabrication_signal = bool(
        promise_guard.PROMISE_RE.search(output)
        and not any(k == "tool_call" for k in step_kinds)
    )

    prompt = build_prompt(
        user_message=run.user_message, spawn_name=run.spawn_name,
        roster=await _roster_text(), persona=persona, output=output,
        fabrication_signal=fabrication_signal,
    )

    try:
        adapter = await build_adapter(role="judge")
        resp = await adapter.chat(system=JUDGE_SYSTEM, user=prompt)
        parsed = parse_json_object(resp.content or "")
        if not isinstance(parsed, dict) or "dimensions" not in parsed:
            raise ValueError("judge returned no dimensions")
        dims_raw = parsed["dimensions"]
        overall = parsed.get("overall", {})
        rows = []
        for dim in _DIMENSIONS:
            status, sc, comment = _coerce_dim(dims_raw.get(dim, {}))
            if dim == "fabrication" and fabrication_signal:
                comment = f"[fabrication_signal] {comment}".rstrip()
            rows.append(RunEvaluation(run_id=run_id, dimension=dim, status=status,
                                      score=sc, comment=comment))
        overall_score = float(overall.get("score", 0))
        badge = str(overall.get("badge", "ok"))
        if badge not in ("good", "ok", "bad"):
            badge = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("run %s scoring failed: %s", run_id, exc)
        async with db_session.AsyncSessionLocal() as db:
            run = await db.get(Run, run_id)
            if run is not None:
                run.status = "score_failed"
                await db.commit()
        return

    async with db_session.AsyncSessionLocal() as db:
        run = await db.get(Run, run_id)
        if run is None:
            return
        run.overall_score = overall_score
        run.overall_badge = badge
        run.status = "scored"
        for r in rows:
            db.add(r)
        await db.commit()
