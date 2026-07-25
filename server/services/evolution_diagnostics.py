"""E9-b: the SINGLE source of truth for evolution eligibility diagnostics — shared by the CLI
(scripts/diagnose_evolution.py) and the GET /spawns/{id}/evolution/diagnosis endpoint.

READ-ONLY: `diagnose_spawn` never writes. It calls `build_corpus(...)` with the DEFAULT
`mint=False`, so inspecting a spawn NEVER mints synthetic tasks or spends tokens. Every rule
reuses the real services (build_corpus, is_replayable, the evolution_watcher._* helpers,
settings_service, replay_set, REPLAY_SAFE_BUILTINS) exactly as the script did — never a
re-derivation — so what the diagnosis reports is what the actual gate/watcher code decides.

The verdict is a stable machine `verdict_code` + a `verdict_params` dict (numbers / tool names
/ attempt id / pre-formatted dates — DATA, never baked English prose), so the inbox panel can
render the sentence per-locale and the CLI can render it in English from the same code.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from server.db.models import EvolutionAttempt, EvolutionProposal, Run, RunStep, Spawn
from server.services import (
    replay_gate,
    replay_run,
    replay_set,
    settings_service,
)
from server.services import evolution_watcher as ew
from server.services.replay_safety import REPLAY_SAFE_BUILTINS

MIN_HOLDOUT_N = replay_gate.MIN_HOLDOUT_N  # 10 (reused, not hard-coded)
WIN_RATE_MIN = replay_gate.WIN_RATE_MIN    # 0.60
HUNG_AGE_SECONDS = 10 * 60                 # an in-flight attempt older than this looks hung

# Reasons the gate/loop can emit that are genuine QUALITY/gate failures (vs a pre-gate
# structural precondition). A recent attempt carrying one of these is a real gate failure.
GATE_REASONS = frozenset({
    "length_cap", "insufficient_holdout", "holdout_winrate", "real_floor",
    "verbose_fail", "no accepted edit beats the original", "insufficient scored runs",
    "gate did not pass",
})


def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)


def _trunc(text, n: int = 200) -> str:
    s = (text or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _is_gate_reason(reason: str) -> bool:
    r = (reason or "").strip()
    return r in GATE_REASONS or r.startswith("dim_regressed") or r.startswith("gate failed")


def _verdict_code(*, total_scored, replayable, non_replayable, offending_tools, baseline,
                  scored_ge_baseline, holdout_ceiling, real_holdout, propose_count,
                  attempts) -> tuple[str, dict]:
    """Deterministic verdict, first matching cause wins (root causes before symptoms). Returns
    a stable machine code + a params dict of the DATA used to render the sentence (numbers, tool
    names, attempt id, pre-formatted dates) — never pre-formatted prose, so the panel renders it
    per-locale and the CLI renders it in English from the same code.

    E9-b (Task 3 interaction): a thin REAL holdout is no longer a blocker. The mint=True
    synthetic top-up fills the holdout side to MIN_HOLDOUT_N at evolve time, so when the
    un-topped holdout ceiling is < MIN_HOLDOUT_N we emit the INFORMATIONAL
    `holdout_via_synthetic_topup` (params {real_holdout, min}) instead of the old blocking
    `drought_holdout_split`. The genuinely-blocking droughts (no runs / non-replayable starving
    the propose side / too few total to optimize) come FIRST in the order and still block."""
    latest = attempts[0] if attempts else None

    # 1. In-flight and old → the runner may be hung (wins over everything).
    if latest is not None and latest.outcome is None and latest.started_at is not None:
        age = (datetime.utcnow() - latest.started_at).total_seconds()
        if age > HUNG_AGE_SECONDS:
            return "in_flight_hung", {"attempt_id": latest.id, "age_min": int(age // 60),
                                      "started_at": _fmt_dt(latest.started_at)}

    # 2. No scored runs at all.
    if total_scored == 0:
        return "drought_no_runs", {}

    # 3. Non-replayable exclusion starves the corpus below the floor (the E9-a case) — this
    #    genuinely starves the PROPOSE side too, which the holdout top-up cannot fix.
    if replayable < MIN_HOLDOUT_N and non_replayable > 0:
        return "drought_non_replayable", {
            "non_replayable": non_replayable, "total_scored": total_scored,
            "replayable": replayable, "min": MIN_HOLDOUT_N, "tools": dict(offending_tools)}

    # 4. Too few raw runs (all replayable, but simply not enough to optimize).
    if total_scored < MIN_HOLDOUT_N:
        return "drought_too_few", {"total_scored": total_scored, "replayable": replayable,
                                   "min": MIN_HOLDOUT_N}

    # 5. A declared baseline floors the eligible set below threshold.
    if baseline is not None and scored_ge_baseline < MIN_HOLDOUT_N and total_scored >= MIN_HOLDOUT_N:
        return "baseline_flooring", {
            "scored_ge_baseline": scored_ge_baseline, "total_scored": total_scored,
            "min": MIN_HOLDOUT_N, "baseline": _fmt_dt(baseline)}

    # 6. Enough replayable raw runs, but the ~40% holdout split can't reach the floor. NOT a
    #    blocker anymore — the mint=True top-up fills it to MIN_HOLDOUT_N on the next evolve.
    if holdout_ceiling < MIN_HOLDOUT_N:
        return "holdout_via_synthetic_topup", {"real_holdout": real_holdout, "min": MIN_HOLDOUT_N}

    # 7. A recent finalized attempt failed on a real gate threshold.
    latest_final = next((a for a in attempts if a.outcome is not None), None)
    if latest_final is not None and latest_final.outcome == "failed" \
            and _is_gate_reason(latest_final.reason):
        return "gate_failure", {"attempt_id": latest_final.id, "reason": latest_final.reason}

    # 8. A recent attempt was skipped for budget.
    if latest_final is not None and latest_final.outcome == "skipped_budget":
        return "skipped_budget", {"attempt_id": latest_final.id, "reason": latest_final.reason}

    # 9. Nothing blocks — the optimizer just may not have beaten the baseline yet, or evolution
    #    hasn't been enqueued.
    return "eligible_looking", {}


async def diagnose_spawn(db, spawn: Spawn) -> dict:
    """Gather every read-only signal for one spawn. Returns a dict the CLI renderer and the
    endpoint both consume. NEVER writes (build_corpus mint defaults to False)."""
    sid = spawn.id

    # (2) Raw epoch>=1 live scored runs — the universe the corpus is drawn from.
    scored_runs = (await db.execute(
        select(Run).where(
            Run.spawn_id == sid, Run.kind == "live", Run.epoch >= 1, Run.status == "scored",
        ).order_by(Run.id)
    )).scalars().all()
    total_scored = len(scored_runs)

    # (3) Replayability — the prime suspect. Reuse replay_run.is_replayable (the SAME function
    # the eligibility count and the gate corpus use). For each NON-replayable run, pull the
    # offending tool names straight from its tool_call steps.
    replayable = 0
    non_replayable_run_ids: list[int] = []
    offending_tools: dict[str, int] = {}
    for run in scored_runs:
        if await replay_run.is_replayable(db, run.id):
            replayable += 1
            continue
        non_replayable_run_ids.append(run.id)
        steps = (await db.execute(
            select(RunStep).where(RunStep.run_id == run.id, RunStep.kind == "tool_call")
        )).scalars().all()
        for s in steps:
            ref = s.ref if isinstance(s.ref, dict) else {}
            tool = ref.get("tool")
            if tool and tool not in REPLAY_SAFE_BUILTINS:
                offending_tools[tool] = offending_tools.get(tool, 0) + 1
    non_replayable = total_scored - replayable

    # Faithfulness self-check: our count must match the watcher's own helper.
    watcher_replayable = await ew._new_replayable_run_count(db, sid, None)

    # (4) Baseline floor.
    baseline = await settings_service.get_baseline_started_at(db)
    if baseline is not None:
        scored_ge_baseline = sum(1 for r in scored_runs if r.created_at and r.created_at >= baseline)
    else:
        scored_ge_baseline = total_scored

    # (5) The corpus the gate actually builds. READ-ONLY: default mint=False, so the synthetic
    # holdout top-up NEVER runs during a diagnosis. `holdout_ceiling` is therefore the un-topped
    # ceiling; `real_holdout` is the truly-real slice; `effective_holdout` projects what the
    # mint=True top-up would reach at evolve time — so the panel is honest.
    corpus = await replay_gate.build_corpus(db, sid, baseline_started_at=None)
    holdout_pairs = [p for p in corpus if p.get("split_side") == "holdout"]
    propose_pairs = [p for p in corpus if p.get("split_side") == "propose"]
    holdout_ceiling = len(holdout_pairs)
    real_holdout = sum(1 for p in holdout_pairs if p.get("corpus_label") == "real")
    corpus_excluded = getattr(corpus, "excluded", 0)
    # Read within THIS session (not the global one) so the whole diagnosis is one consistent,
    # read-only source — the endpoint's request session and the CLI's read-only engine both work.
    replay_items = await replay_set.build(sid, cap=64, db=db)

    # (6) Last 5 attempts (newest first).
    attempts = (await db.execute(
        select(EvolutionAttempt).where(EvolutionAttempt.spawn_id == sid)
        .order_by(EvolutionAttempt.id.desc()).limit(5)
    )).scalars().all()

    # (7) Backoff state — reuse the watcher's own math.
    consec_fails = await ew._consecutive_fails(db, sid)
    threshold = ew._threshold(consec_fails)
    last_started = await ew._last_attempt_started_at(db, sid)
    count_since = await ew._new_replayable_run_count(db, sid, last_started)
    auto_eligible = count_since >= threshold

    # Any existing proposals? ("No evolution proposals yet" == none open/proposed.)
    open_props = (await db.execute(
        select(func.count()).select_from(EvolutionProposal).where(
            EvolutionProposal.spawn_id == sid,
            EvolutionProposal.status.in_(("open", "proposed")),
        )
    )).scalar() or 0

    verdict_code, verdict_params = _verdict_code(
        total_scored=total_scored, replayable=replayable, non_replayable=non_replayable,
        offending_tools=offending_tools, baseline=baseline,
        scored_ge_baseline=scored_ge_baseline, holdout_ceiling=holdout_ceiling,
        real_holdout=real_holdout, propose_count=len(propose_pairs), attempts=attempts,
    )

    # effective_holdout projects the mint=True top-up ONLY when that top-up is genuinely the next
    # step — i.e. the headline verdict IS `holdout_via_synthetic_topup`. Under any upstream blocker
    # (no runs / non-replayable / too few / baseline flooring / in-flight) the honest number is the
    # real un-topped ceiling; don't dangle "→ MIN after top-up" next to a hard drought.
    if verdict_code == "holdout_via_synthetic_topup":
        effective_holdout = MIN_HOLDOUT_N
    else:
        effective_holdout = holdout_ceiling

    # Globals surfaced for the endpoint payload (one place, one call).
    auto_on = await settings_service.evolution_auto(db)
    max_dispatches = await settings_service.evolution_max_dispatches(db)
    # Non-null only on an install that had set the removed token cap: its limit is NOT
    # being carried over (the unit changed), and it deserves to hear that from the UI.
    legacy_token_cap = await settings_service.legacy_token_cap_if_set(db)

    # Endpoint-safe plain dicts (ISO strings) — never leak ORM objects out of the request.
    last_attempts = [{
        "id": a.id, "outcome": a.outcome, "reason": a.reason or "",
        "started_at": a.started_at.isoformat() if a.started_at else None,
        "finished_at": a.finished_at.isoformat() if a.finished_at else None,
    } for a in attempts]

    return {
        # CLI-facing (ORM objects retained for the rich section-6 render; never serialized).
        "spawn": spawn, "attempts": attempts, "baseline": baseline,
        "non_replayable_run_ids": non_replayable_run_ids, "watcher_replayable": watcher_replayable,
        "replay_items": len(replay_items), "last_started": last_started,
        # Shared numeric fields.
        "total_scored": total_scored, "replayable": replayable, "non_replayable": non_replayable,
        "offending_tools": offending_tools, "scored_ge_baseline": scored_ge_baseline,
        "corpus_total": len(corpus), "holdout_ceiling": holdout_ceiling,
        "real_holdout": real_holdout, "effective_holdout": effective_holdout,
        "propose_count": len(propose_pairs), "corpus_excluded": corpus_excluded,
        "consec_fails": consec_fails, "threshold": threshold, "count_since": count_since,
        "auto_eligible": auto_eligible, "open_props": open_props,
        # Endpoint-facing extras.
        "generation_level": spawn.generation_level, "min_holdout_n": MIN_HOLDOUT_N,
        "auto_on": auto_on, "max_dispatches": max_dispatches,
        "legacy_token_cap_dropped": legacy_token_cap, "last_attempts": last_attempts,
        "verdict_code": verdict_code, "verdict_params": verdict_params,
    }
