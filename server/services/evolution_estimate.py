"""Cost estimate for one background evolution attempt (S2 E5, acceptance d / audit #13).

🔴 TWO SETS OF NUMBERS LIVE HERE, AND THEY DISAGREE ON PURPOSE.

The ORIGINAL fields (`dispatches`, `judge_calls`, `est_tokens`, `lower_bound: True`) are
FROZEN. They are wrong — `dispatches` multiplies the WHOLE corpus by `epochs*lr_budget+1`,
but the optimizer never replays the whole corpus: it replays the val slice, capped at
`val_cap`, and the holdout never enters the optimizer at all. Only the final gate touches
every pair. So the number is close to a floor on a small corpus and an increasingly large
OVER-estimate as the corpus grows.

They are frozen anyway, because `evolution_watcher` compares `est_tokens` against
`evolution_max_dispatches` against `dispatches_max` (:259) — but `est_tokens` remains on
the payload and on screen. Repricing it with the correct population would drop it
to roughly 1/2.5 — no code change beside the gate, but the number the gate compares moves,
which is silently loosening a spend gate by 2.5x. The executing side fails closed; a
frozen wrong number that keeps today's behaviour beats a better number that quietly
widens the gate. The gate's own fix is a separate project.

The NEW fields (`dispatches_max`, `judge_calls_max`, `basis: "max"`) are DERIVED from the
loop rather than restating it — that was the root cause: the old estimate paraphrased the
loop's behaviour in prose instead of reading it. `_loop_defaults` now reads `val_cap` from
the signature alongside epochs/lr_budget, because the ceiling turns on it.

What `basis: "max"` covers and does NOT cover:
  * covers the three COUNT fields, and only those;
  * `tokens_projected` is a mean-priced projection, NOT a bound — an average times a count
    bounds nothing (a single replay in this repo's own data ranges 13,394..91,025 tokens);
  * the ceiling is over the corpus AT ESTIMATE TIME. `build_corpus` has no LIMIT, so a run
    scored between the estimate and the attempt adds 2 more gate dispatches;
  * NOT priced at all: the optimizer's per-epoch call (it sends the whole doc, up to
    MAX_PROMPT_LEN), minting's generation calls, and the embedding call `snapshot_ambient`
    makes once per gate pair;
  * `avg_replay_tokens` / `avg_replay_n` are POOLED ACROSS ALL SPAWNS, not this spawn's,
    even though they are returned inside a per-spawn estimate. The ledger is too thin to
    slice. A reader who takes the name at face value gets a number about a different
    population than they think — the failure this whole round exists to end, in miniature.
Nothing here may be read as "evolution spend is bounded".
"""
from __future__ import annotations

import inspect

from sqlalchemy import select

from server.db.models import EvolutionAttempt, Run
from server.services import evolution_loop, replay_gate

# A single compare-judge LLM call reads the task + persona + BOTH arms' outputs + the
# rubric. We cannot know the exact size before the run, so this is a conservative per-call
# floor used only to price judge_calls; it is explicitly part of the labelled lower bound.
AVG_JUDGE_TOKENS = 800


def _loop_defaults() -> tuple[int, int, int]:
    """Read epochs / lr_budget / val_cap straight from propose_improvement's signature so
    the estimate can never drift from the loop it is estimating.

    `val_cap` joins the other two because the derived ceiling TURNS on it: the optimizer
    never replays the whole corpus, it replays the val slice, and val is capped here. A
    ceiling that hardcoded 8 would stop being a ceiling the moment someone raised the cap
    — it would be a number that happened to be right once."""
    sig = inspect.signature(evolution_loop.propose_improvement)
    return (int(sig.parameters["epochs"].default),
            int(sig.parameters["lr_budget"].default),
            int(sig.parameters["val_cap"].default))


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



async def _avg_replay_tokens(db) -> tuple[float | None, int]:
    """Mean tokens per SUCCESSFUL replay dispatch, from the `actual` ledger.

    🔴 POOLED ACROSS ALL SPAWNS, deliberately — note the absent `spawn_id` parameter,
    unlike `_avg_run_tokens(db, spawn_id)` right above. The ledger is nearly empty (zero
    rows on every install today), so slicing it per spawn would return None for almost
    everyone. The caller returns it inside a PER-SPAWN estimate, so the name alone reads
    as "this spawn's average"; it is not, and every place it surfaces says so.

    🔴 Deliberately NOT `SELECT avg(task_tokens) FROM runs WHERE spawn_id=? AND
    kind='replay'`. skill_forge drives the SAME `replay_gate.run_gate` and reuses the same
    `REPLAY_CONVERSATION_ID` (replay_gate.py:69), so its replay rows are identical to
    evolution's on spawn_id, kind AND conversation_id — there is no column to discriminate
    on, and no filter can rescue that join. evolution_watcher's own comment states the rule
    the other way round: sum "by identity, never by a spawn_id/time-window join that would
    absorb skill_forge's concurrent replays for the same spawn."

    Each `actual.dispatch_tokens` was summed by exactly that identity rule — from the run
    ids `collect_run_ids()` observed during that one attempt — so aggregating over attempts
    inherits the property instead of re-opening the hole.

    The denominator subtracts `failed_dispatches`: a failed dispatch contributes zero or
    partial tokens, and leaving it in would deflate the mean, while the estimate multiplies
    by PLANNED dispatches (which assume success). Returns (None, 0) when the ledger is
    empty — which it is today, on every install, because `actual` has never been written.
    """
    rows = (await db.execute(select(EvolutionAttempt.actual))).scalars().all()
    tokens = 0
    successes = 0
    for a in rows:
        if not isinstance(a, dict):
            continue
        d = int(a.get("dispatches") or 0)
        if d <= 0:
            continue
        ok = d - int(a.get("failed_dispatches") or 0)
        if ok <= 0:
            continue
        tokens += int(a.get("dispatch_tokens") or 0)
        successes += ok
    if successes == 0:
        return None, 0
    return tokens / successes, successes

async def estimate(db, spawn_id: int) -> dict:
    """A labelled lower-bound cost estimate for one evolution attempt on `spawn_id`.

    Returns {pairs, dispatches, judge_calls, optimizer_calls, synth_calls, est_tokens,
    lower_bound: True}. `pairs` = the whole paired corpus (propose ∪ holdout)."""
    epochs, lr_budget, val_cap = _loop_defaults()

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

    # ── derived ceiling (new fields; everything above is FROZEN, see the module note) ──
    # V = the val slice the optimizer actually replays. _subsplit_propose sends every third
    # PROPOSE item to val (idx % 3 == 2) and then truncates at val_cap, so it is
    # floor(propose/3) — not ceil. Holdout never enters the optimizer at all.
    propose_pairs = sum(1 for p in corpus if p.get("split_side") == "propose")
    val_pairs = min(val_cap, propose_pairs // 3)

    # Derived from the loop, term by term:
    #   _val_outputs   V per epoch, at most once per epoch (guarded by doc != last_best_doc)
    #   evaluate       V per candidate, at most epochs*lr_budget candidates
    #   run_gate       2 per pair over the WHOLE corpus, called exactly once
    candidates_max = epochs * lr_budget
    dispatches_max = val_pairs * epochs + val_pairs * candidates_max + 2 * pairs
    judge_calls_max = 2 * val_pairs * candidates_max + 2 * pairs

    # 🔴 No *_min fields. The true minimum is ZERO — propose_improvement returns before any
    # dispatch when the spawn is gone (evolution_loop.py:94) or when the val slice is empty
    # (:115), and attempt 7 in the wild took exactly that second path. Emitting a constant 0
    # would invite someone to treat it as information.
    # Pooled over EVERY spawn's completed attempts, not this one's — see the helper.
    avg_replay, avg_replay_n = await _avg_replay_tokens(db)
    tokens_projected = (
        int(avg_replay * dispatches_max + AVG_JUDGE_TOKENS * judge_calls_max)
        if avg_replay is not None else None
    )

    return {
        # ── frozen: same keys, same arithmetic, same meaning as before this round ──
        "pairs": pairs,
        "dispatches": dispatches,
        "judge_calls": judge_calls,
        "optimizer_calls": optimizer_calls,
        "synth_calls": synth_calls,
        "est_tokens": est_tokens,
        "lower_bound": True,
        # ── new, additive: a ceiling that is actually derived ──
        "propose_pairs": propose_pairs,
        "val_pairs": val_pairs,
        "dispatches_max": dispatches_max,
        "judge_calls_max": judge_calls_max,
        "optimizer_calls_max": epochs,
        # `basis` describes the three COUNT fields above and nothing else. It does NOT
        # describe tokens_projected, which is a mean-priced projection, not a bound.
        "basis": "max",
        "avg_replay_tokens": avg_replay,
        "avg_replay_n": avg_replay_n,
        "tokens_projected": tokens_projected,
        "tokens_projected_unavailable_reason": (
            None if tokens_projected is not None else "no_completed_attempts_with_actual"),
    }
