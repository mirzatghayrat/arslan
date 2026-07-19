"""Cost estimate for one background evolution attempt (S2 E5, acceptance d / audit #13).

🔴 THIS IS NOT A RELIABLE LOWER BOUND, despite the `lower_bound: True` field and what
this docstring used to claim. `dispatches` below multiplies the WHOLE corpus by
`epochs*lr_budget + 1`, but the optimizer never replays the whole corpus: evolution_loop
splits the propose side and caps it at `val_cap=8`, and the holdout never enters the
optimizer at all. Only the final gate touches every pair. So the number is close to a
floor on a SMALL corpus and an increasingly large OVER-estimate as the corpus grows —
and `build_corpus` has no cap, so it only grows.

Two consequences that must not be forgotten while this stands:
  * do not present it as a forecast, and do not let UI copy call it a floor
    (the six locale strings were corrected to say exactly this);
  * do not build a spend gate on it. A fixed cap over a monotonically growing number is
    a permanent kill switch that fires FIRST on the most-used spawns and never unfires.
    `evolution_max_est_tokens` therefore stays unset (no cap) — better no gate than a
    gate built on a number we know is wrong.

Fixing it is its own project, and the fix must be structural: read the loop's real caps
the way `_loop_defaults` already reads epochs/lr_budget from the signature, and assert
the projected dispatch count against a dry run over a synthetic corpus. The root cause
here is that the estimate RESTATES the loop's behavior in prose instead of deriving it.

What is still true: it prices dispatches with the per-run token average of REAL live
turns, and it deliberately excludes retries, the optimizer's own LLM turns
(`optimizer_calls` is surfaced but not tokened), and any synthetic-generation cost (E6) —
so those omissions push in the floor direction, while the dispatch overcount pushes the
other way and dominates once the corpus is large.

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

    # READ-ONLY: mint=False so merely previewing a cost never mutates the corpus or spends
    # generation tokens (E9-b). But keep the estimate HONEST — project the synthetic holdout
    # top-up the REAL run (mint=True) would do, WITHOUT minting: when the real holdout is below
    # the floor, the gate will top the holdout up to MIN_HOLDOUT_N, so add those projected pairs
    # to the pair/dispatch/judge counts (mirrors replay_gate.build_corpus's mint condition
    # exactly). The generation LLM cost of minting is still excluded (surfaced via lower_bound).
    corpus = await replay_gate.build_corpus(db, spawn_id, baseline_started_at=None)
    real_holdout = sum(1 for p in corpus
                       if p["corpus_label"] == "real" and p["split_side"] == "holdout")
    total_holdout = sum(1 for p in corpus if p["split_side"] == "holdout")
    proj_topup = (replay_gate.MIN_HOLDOUT_N - total_holdout) if (
        real_holdout < replay_gate.MIN_HOLDOUT_N
        and total_holdout < replay_gate.MIN_HOLDOUT_N) else 0
    pairs = len(corpus) + proj_topup

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
