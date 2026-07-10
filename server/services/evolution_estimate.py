"""Honest LOWER-BOUND cost estimate for one background evolution attempt (S2 E5,
acceptance d / audit #13).

Every number here is a floor, not a forecast: it counts the dispatches/judge calls the
propose→gate flow provably makes with the loop defaults, and prices them with the
per-run token average of REAL live turns. It deliberately excludes retries, the
optimizer's own LLM turns (`optimizer_calls` is surfaced but not tokened), and any
synthetic-generation cost (E6). Callers surface `lower_bound: True` so the UI never
presents it as a ceiling.

The one subtlety worth repeating (spec §E4 note): a proposal pays for BOTH the optimizer
epoch loop AND the final gate replay, so a single pair is dispatched
`2 * (epochs*lr_budget + 1)` times — `epochs*lr_budget` bounded-edit evaluations plus one
final gate replay, times two arms.

`avg_run_tokens` is computed ONLY over `epoch>=1 AND kind='live' AND task_tokens>0` runs:
the live DB has most historical rows at task_tokens=0 (streaming spawns never reported), so
an unfiltered average is ~4x too low and would understate the estimate.
"""
from __future__ import annotations

import inspect

from sqlalchemy import select

from server.db.models import Run
from server.services import evolution_loop, replay_gate

# A single compare-judge LLM call reads the task + persona + BOTH arms' outputs + the
# rubric. We cannot know the exact size before the run, so this is a conservative per-call
# floor used only to price judge_calls; it is explicitly part of the labelled lower bound.
AVG_JUDGE_TOKENS = 800


def _loop_defaults() -> tuple[int, int]:
    """Read epochs / lr_budget straight from propose_improvement's signature so the
    estimate can never drift from the loop it is estimating."""
    sig = inspect.signature(evolution_loop.propose_improvement)
    epochs = sig.parameters["epochs"].default
    lr_budget = sig.parameters["lr_budget"].default
    return int(epochs), int(lr_budget)


async def _avg_run_tokens(db, spawn_id: int) -> float:
    """Mean task_tokens over this spawn's clean live turns that actually reported tokens
    (`epoch>=1 AND kind='live' AND task_tokens>0`). Zero-token rows are EXCLUDED so a
    fleet full of streaming-era 0s cannot deflate the estimate. No qualifying run → 0.0."""
    rows = (await db.execute(
        select(Run.task_tokens).where(
            Run.spawn_id == spawn_id,
            Run.kind == "live",
            Run.epoch >= 1,
            Run.task_tokens > 0,
        )
    )).scalars().all()
    return (sum(rows) / len(rows)) if rows else 0.0


async def estimate(db, spawn_id: int) -> dict:
    """A labelled lower-bound cost estimate for one evolution attempt on `spawn_id`.

    Returns {pairs, dispatches, judge_calls, optimizer_calls, synth_calls, est_tokens,
    lower_bound: True}. `pairs` = the whole paired corpus (propose ∪ holdout)."""
    epochs, lr_budget = _loop_defaults()

    corpus = await replay_gate.build_corpus(db, spawn_id, baseline_started_at=None)
    pairs = len(corpus)

    # Both the optimizer's bounded-edit evaluations AND the final gate replay dispatch each
    # pair twice (baseline arm + candidate arm) — spec §E4 note.
    per_pair_replays = epochs * lr_budget + 1
    dispatches = pairs * 2 * per_pair_replays
    comparisons = pairs * per_pair_replays          # one compare per replayed pair
    judge_calls = comparisons * 2                   # position-swap = 2 LLM calls per compare
    optimizer_calls = epochs
    synth_calls = 0                                 # synthetic generation (E6) not costed here

    avg_run = await _avg_run_tokens(db, spawn_id)
    est_tokens = int(avg_run * dispatches + AVG_JUDGE_TOKENS * judge_calls)

    return {
        "pairs": pairs,
        "dispatches": dispatches,
        "judge_calls": judge_calls,
        "optimizer_calls": optimizer_calls,
        "synth_calls": synth_calls,
        "est_tokens": est_tokens,
        "lower_bound": True,
    }
