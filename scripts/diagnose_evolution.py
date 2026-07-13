#!/usr/bin/env python3
"""READ-ONLY evolution diagnostic — why a spawn shows "No evolution proposals yet".

Run this against YOUR live instance's brain (it does NOT touch the running server; it
opens the SQLite file directly and STRICTLY read-only). It reuses the REAL eligibility
and gate helpers the watcher/loop use — it never re-derives the rules — so what it prints
is what the actual code decides.

    cd <your arslan repo>
    PYTHONPATH=$PWD ARSLAN_SECRET_KEY=<anything> ARSLAN_DATA_DIR=data \
        .venv/bin/python scripts/diagnose_evolution.py --spawn "Research Analyst"

Flags:
    --spawn SUBSTR   Highlight (and only fully dump) spawns whose name contains SUBSTR
                     (case-insensitive). Omit to dump every spawn.
    --db PATH        Diagnose a specific sqlite file instead of the env-resolved brain.

READ-ONLY GUARANTEE (defence in depth):
  * The app's AsyncSessionLocal is repointed at a private engine whose every connection
    runs `PRAGMA query_only=ON` — SQLite itself rejects any write, so even a buggy helper
    cannot mutate your brain.
  * The script only ever calls SELECT-shaped helpers (is_replayable, build_corpus,
    replay_set.build, settings_service getters) and reads Run/RunStep/EvolutionAttempt
    rows. It never calls _create_attempt / enqueue / set_* / commit.

Nothing here decrypts anything, so ARSLAN_SECRET_KEY can be any placeholder.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# ── Read-only engine install (must happen before any helper opens a session) ──────────
# We import the app's session module and REPOINT its engine + sessionmaker at a private
# read-only engine. Helpers that open their own session (e.g. replay_set.build does
# `db_session.AsyncSessionLocal()`) look the attribute up at call time, so this covers
# them too. query_only=ON makes the guarantee enforced by SQLite, not just by discipline.
from sqlalchemy import event, func, select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from server.config import settings  # noqa: E402
from server.db import session as db_session  # noqa: E402
from server.db.models import (  # noqa: E402
    ArslanMessage,
    EvolutionAttempt,
    EvolutionProposal,
    Run,
    RunStep,
    Spawn,
)
from server.services import replay_gate, replay_run, replay_set, settings_service  # noqa: E402
from server.services.replay_safety import REPLAY_SAFE_BUILTINS  # noqa: E402
from server.services import evolution_watcher as ew  # noqa: E402

MIN_HOLDOUT_N = replay_gate.MIN_HOLDOUT_N  # 10 (reused, not hard-coded)
WIN_RATE_MIN = replay_gate.WIN_RATE_MIN    # 0.60
HUNG_AGE_SECONDS = 10 * 60                  # an in-flight attempt older than this looks hung


def install_readonly_engine(db_path: str):
    """Repoint db_session at a private engine that physically refuses writes."""
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _readonly_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA query_only=ON")   # SQLite rejects any write on this connection
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    db_session.engine = engine
    db_session.AsyncSessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine


# ── small helpers ─────────────────────────────────────────────────────────────────────

def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)


def _trunc(text, n: int = 200) -> str:
    s = (text or "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


GATE_REASONS = frozenset({
    "length_cap", "insufficient_holdout", "holdout_winrate", "real_floor",
    "verbose_fail", "no accepted edit beats the original", "insufficient scored runs",
    "gate did not pass",
})


def _is_gate_reason(reason: str) -> bool:
    r = (reason or "").strip()
    return r in GATE_REASONS or r.startswith("dim_regressed") or r.startswith("gate failed")


# ── per-spawn diagnosis ────────────────────────────────────────────────────────────────

async def diagnose_spawn(db, spawn: Spawn) -> dict:
    """Gather every read-only signal for one spawn. Returns a dict the printer renders."""
    sid = spawn.id

    # (2) Raw epoch>=1 live scored runs — the universe the corpus is drawn from.
    scored_runs = (await db.execute(
        select(Run).where(
            Run.spawn_id == sid, Run.kind == "live", Run.epoch >= 1, Run.status == "scored",
        ).order_by(Run.id)
    )).scalars().all()
    total_scored = len(scored_runs)

    # (3) Replayability — the prime suspect. Reuse replay_run.is_replayable (the SAME
    # function the eligibility count and the gate corpus use). For each NON-replayable run,
    # pull the offending tool names straight from its tool_call steps.
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

    # (5) The corpus the gate actually builds (replayable + baseline floor + propose/holdout
    # split). This is the authoritative answer to "can the gate reach 10 holdout pairs?".
    corpus = await replay_gate.build_corpus(db, sid, baseline_started_at=None)
    holdout_pairs = [p for p in corpus if p.get("split_side") == "holdout"]
    propose_pairs = [p for p in corpus if p.get("split_side") == "propose"]
    corpus_excluded = getattr(corpus, "excluded", 0)
    # Also reuse replay_set.build (the optimizer's rich-baseline items) as requested.
    replay_items = await replay_set.build(sid, cap=64)

    # (6) Last 5 attempts.
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

    verdict, verdict_detail = _verdict(
        total_scored=total_scored, replayable=replayable, non_replayable=non_replayable,
        offending_tools=offending_tools, baseline=baseline,
        scored_ge_baseline=scored_ge_baseline, holdout_ceiling=len(holdout_pairs),
        propose_count=len(propose_pairs), attempts=attempts,
    )

    return {
        "spawn": spawn, "total_scored": total_scored, "replayable": replayable,
        "non_replayable": non_replayable, "non_replayable_run_ids": non_replayable_run_ids,
        "offending_tools": offending_tools, "watcher_replayable": watcher_replayable,
        "baseline": baseline, "scored_ge_baseline": scored_ge_baseline,
        "corpus_total": len(corpus), "holdout_ceiling": len(holdout_pairs),
        "propose_count": len(propose_pairs), "corpus_excluded": corpus_excluded,
        "replay_items": len(replay_items), "attempts": attempts,
        "consec_fails": consec_fails, "threshold": threshold,
        "count_since": count_since, "last_started": last_started,
        "auto_eligible": auto_eligible, "open_props": open_props,
        "verdict": verdict, "verdict_detail": verdict_detail,
    }


def _verdict(*, total_scored, replayable, non_replayable, offending_tools, baseline,
             scored_ge_baseline, holdout_ceiling, propose_count, attempts) -> tuple[str, str]:
    """Deterministic verdict. First matching cause wins (root causes before symptoms)."""
    latest = attempts[0] if attempts else None

    # 1. In-flight and old → the runner may be hung.
    if latest is not None and latest.outcome is None and latest.started_at is not None:
        age = (datetime.utcnow() - latest.started_at).total_seconds()
        if age > HUNG_AGE_SECONDS:
            return ("IN-FLIGHT/POSSIBLY HUNG",
                    f"attempt #{latest.id} started {_fmt_dt(latest.started_at)} "
                    f"({int(age // 60)} min ago) and never finalized.")

    # 2. No scored runs at all.
    if total_scored == 0:
        return ("CORPUS DROUGHT — too few runs",
                "0 epoch>=1 live scored runs exist for this spawn.")

    # 3. Non-replayable exclusion is what starves the corpus (the E9-a case).
    if replayable < MIN_HOLDOUT_N and non_replayable > 0:
        tools = ", ".join(f"{t}×{c}" for t, c in sorted(
            offending_tools.items(), key=lambda kv: -kv[1])) or "(unnamed tools)"
        return ("CORPUS DROUGHT — non-replayable",
                f"{non_replayable}/{total_scored} scored runs are NOT hermetically "
                f"replayable → excluded from the corpus (replayable={replayable} < "
                f"{MIN_HOLDOUT_N}). Offending tools: {tools}.")

    # 4. Too few raw runs (all replayable, but simply not enough).
    if total_scored < MIN_HOLDOUT_N:
        return ("CORPUS DROUGHT — too few runs",
                f"only {total_scored} scored runs (< {MIN_HOLDOUT_N}); "
                f"replayable={replayable}.")

    # 5. A declared baseline floors the eligible set below threshold.
    if baseline is not None and scored_ge_baseline < MIN_HOLDOUT_N and total_scored >= MIN_HOLDOUT_N:
        return ("BASELINE FLOORING CORPUS",
                f"declared baseline {_fmt_dt(baseline)} floors the corpus to "
                f"{scored_ge_baseline} runs (< {MIN_HOLDOUT_N}) out of {total_scored} scored.")

    # 6. Enough replayable raw runs, but the ~40% holdout split can't reach 10 pairs.
    if holdout_ceiling < MIN_HOLDOUT_N:
        return ("CORPUS DROUGHT — holdout split too small",
                f"corpus holdout side has only {holdout_ceiling} pairs (< {MIN_HOLDOUT_N}); "
                f"the gate's threshold-1 (insufficient_holdout) can never pass. Add more "
                f"replayable real runs and/or synthetic holdout tasks.")

    # 7. A recent attempt failed on a real gate threshold.
    latest_final = next((a for a in attempts if a.outcome is not None), None)
    if latest_final is not None and latest_final.outcome == "failed" and _is_gate_reason(latest_final.reason):
        return ("GATE FAILURE",
                f"attempt #{latest_final.id} failed: {_trunc(latest_final.reason, 300)}")

    # 8. A recent attempt was skipped for budget.
    if latest_final is not None and latest_final.outcome == "skipped_budget":
        return ("SKIPPED_BUDGET",
                f"attempt #{latest_final.id} skipped: {_trunc(latest_final.reason, 300)}")

    return ("ELIGIBLE-LOOKING — investigate attempt runner",
            "corpus can reach the holdout floor and no attempt records a blocking reason; "
            "the optimizer may simply not have found an edit that beats the baseline yet, "
            "or auto is off / no manual ENQUEUE has run.")


# ── printing ────────────────────────────────────────────────────────────────────────────

def print_spawn(d: dict, *, highlighted: bool) -> None:
    s = d["spawn"]
    star = " ◀── matched --spawn" if highlighted else ""
    print("=" * 78)
    print(f"[1] spawn #{s.id}  {s.name!r}  (gen {s.generation_level}){star}")
    print(f"[2] epoch>=1 live scored runs (raw):        {d['total_scored']}")

    rep = d["replayable"]
    print(f"[3] hermetically REPLAYABLE runs:           {rep}"
          f"    (watcher helper agrees: {d['watcher_replayable']})")
    print(f"    NON-replayable (excluded from corpus):  {d['non_replayable']}")
    if d["offending_tools"]:
        tools = ", ".join(f"{t} ×{c}" for t, c in sorted(
            d["offending_tools"].items(), key=lambda kv: -kv[1]))
        print(f"    ↳ non-replay-safe tools that caused exclusion: {tools}")
        print(f"    ↳ replay-safe builtins allowed: {', '.join(sorted(REPLAY_SAFE_BUILTINS))}")
        if d["non_replayable_run_ids"]:
            ids = d["non_replayable_run_ids"]
            shown = ", ".join(str(i) for i in ids[:12]) + (" …" if len(ids) > 12 else "")
            print(f"    ↳ non-replayable run ids: {shown}")

    if d["baseline"] is not None:
        print(f"[4] clean-corpus baseline declared:         {_fmt_dt(d['baseline'])}")
        print(f"    scored runs at/after baseline:          {d['scored_ge_baseline']}")
    else:
        print("[4] clean-corpus baseline declared:         NOT declared "
              "(no floor applied — permissive, cannot be the cause)")

    print(f"[5] gate corpus (build_corpus) total pairs: {d['corpus_total']}"
          f"   (real replayable + active synthetic)")
    print(f"    ├─ propose-side pairs:                  {d['propose_count']}"
          f"    (optimizer needs ≥3 here for a val set)")
    print(f"    └─ HOLDOUT-side pairs (ceiling):        {d['holdout_ceiling']}"
          f"    vs MIN_HOLDOUT_N={MIN_HOLDOUT_N} "
          f"{'✓ can reach' if d['holdout_ceiling'] >= MIN_HOLDOUT_N else '✗ CANNOT reach'}")
    print(f"    replay_set.build items available:       {d['replay_items']}")
    print(f"    build_corpus non-replayable exclusions: {d['corpus_excluded']}")

    print("[6] last 5 EvolutionAttempts (newest first):")
    if not d["attempts"]:
        print("    (none — no attempt has ever run for this spawn)")
    else:
        for a in d["attempts"]:
            outcome = a.outcome if a.outcome is not None else "in-flight"
            print(f"    #{a.id}  start={_fmt_dt(a.started_at)}  end={_fmt_dt(a.finished_at)}  "
                  f"outcome={outcome}")
            if a.reason:
                print(f"         reason: {_trunc(a.reason, 200)}")

    print(f"[7] consecutive_fails={d['consec_fails']}  →  auto threshold={d['threshold']}")
    print(f"    new replayable runs since last attempt: {d['count_since']}  "
          f"→ auto-eligible: {'YES' if d['auto_eligible'] else 'no'}")
    print(f"    open/proposed proposals right now:      {d['open_props']}")

    print(f"[8] VERDICT: {d['verdict']}")
    print(f"    {d['verdict_detail']}")


def summary_paragraph(d: dict, *, auto_on: bool, max_est) -> str:
    s = d["spawn"]
    parts = [f"Spawn '{s.name}' (#{s.id}) has {d['total_scored']} epoch>=1 live scored runs, "
             f"of which {d['replayable']} are hermetically replayable and {d['non_replayable']} "
             f"are excluded."]
    if d["offending_tools"]:
        tools = ", ".join(sorted(d["offending_tools"].keys()))
        parts.append(f"The excluded runs used non-replay-safe tools ({tools}) — evolution "
                     f"only replays runs whose tools are all in the safe builtin set "
                     f"({', '.join(sorted(REPLAY_SAFE_BUILTINS))}), so those runs never enter "
                     f"the corpus.")
    parts.append(f"The gate needs {MIN_HOLDOUT_N} non-tie HOLDOUT pairs; the current corpus "
                 f"holdout ceiling is {d['holdout_ceiling']} "
                 f"({d['propose_count']} on the propose side).")
    if d["baseline"] is None:
        parts.append("No clean-corpus baseline is declared (no date floor is applied).")
    else:
        parts.append(f"A baseline of {_fmt_dt(d['baseline'])} is declared, leaving "
                     f"{d['scored_ge_baseline']} runs at/after it.")
    if not d["attempts"]:
        parts.append("No background evolution attempt has ever run for this spawn "
                     f"(auto is {'ON' if auto_on else 'OFF'}; auto-eligible now: "
                     f"{'yes' if d['auto_eligible'] else 'no'}).")
    else:
        a = d["attempts"][0]
        parts.append(f"The latest attempt (#{a.id}) outcome is "
                     f"{a.outcome or 'in-flight'}.")
    if max_est is not None:
        parts.append(f"The per-attempt token budget cap is {max_est}.")
    parts.append(f"VERDICT: {d['verdict']} — {d['verdict_detail']}")
    return " ".join(parts)


# ── driver ──────────────────────────────────────────────────────────────────────────────

async def run(spawn_substr: str | None) -> int:
    async with db_session.AsyncSessionLocal() as db:
        auto_on = await settings_service.evolution_auto(db)
        max_est = await settings_service.evolution_max_est_tokens(db)
        spawns = (await db.execute(select(Spawn).order_by(Spawn.id))).scalars().all()

        print(f"Brain: {settings.db_path}")
        print(f"evolution_auto={'ON' if auto_on else 'OFF'}   "
              f"evolution_max_est_tokens={max_est if max_est is not None else 'unset (no cap)'}   "
              f"MIN_HOLDOUT_N={MIN_HOLDOUT_N}   WIN_RATE_MIN={WIN_RATE_MIN}")
        print(f"{len(spawns)} spawn(s) in this brain.\n")

        if not spawns:
            print("No spawns found — nothing to diagnose.")
            return 0

        needle = (spawn_substr or "").lower().strip()
        targeted = [s for s in spawns if needle and needle in (s.name or "").lower()]
        to_dump = targeted if targeted else spawns

        diags = []
        focus = None
        for s in to_dump:
            d = await diagnose_spawn(db, s)
            diags.append(d)
            is_match = bool(needle) and s in targeted
            if is_match and focus is None:
                focus = d
            print_spawn(d, highlighted=is_match)
            print()

        if needle and not targeted:
            print(f"(no spawn name contained {spawn_substr!r}; dumped all spawns above)\n")

        if focus is None:
            focus = diags[0]

    print("=" * 78)
    print("PLAIN-ENGLISH SUMMARY (paste this back):")
    print(summary_paragraph(focus, auto_on=auto_on, max_est=max_est))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only evolution diagnostic.")
    ap.add_argument("--spawn", default=None,
                    help="Highlight spawns whose name contains this substring "
                         "(e.g. 'Research Analyst'). Omit to dump all spawns.")
    ap.add_argument("--db", default=None,
                    help="Diagnose a specific sqlite file instead of the env-resolved brain.")
    args = ap.parse_args(argv)

    db_path = args.db or settings.db_path
    if not Path(db_path).exists():
        print(f"ERROR: database file not found: {db_path}", file=sys.stderr)
        print("Set ARSLAN_DATA_DIR to your instance's data dir (the one holding arslan.db), "
              "or pass --db <path>.", file=sys.stderr)
        return 2
    # Keep settings.db_path in sync for the header when --db is used.
    if args.db:
        object.__setattr__(settings, "db_path", db_path)

    install_readonly_engine(db_path)
    return asyncio.run(run(args.spawn))


if __name__ == "__main__":
    raise SystemExit(main())
