"""ReplayGate — the paired win-rate gate that decides whether an evolution proposal
is REAL (S2 E4, the methodology core).

For a candidate prompt vs the baseline prompt, the gate replays BOTH arms on the same
corpus of tasks (each pair sharing one ambient snapshot, spec §E3/#16), judges each pair
with the position-swap compare judge, and applies the thresholds below. The single
non-negotiable rule the whole design turns on:

    EVERY user-facing threshold is computed on HOLDOUT pairs ONLY. The propose pairs
    feed only `GateResult.internal_signal()` (the optimizer's iteration signal). Asking
    for a user-facing win-rate from propose pairs raises HoldoutViolation — enforced in
    code (`compute_delta` asserts split_side=='holdout'), not merely by convention.

A/B → win polarity (PINNED): the baseline is arm A (output_a), the candidate is arm B
(output_b) — matching evaluator._bump and compare_judge's merge semantics. So compare's
`overall`/dim value 'b' == CANDIDATE win, 'a' == candidate LOSS (baseline win), 'tie' == tie.
(Verified against tests/server/test_compare_evidence.py: pass1 slot1='a' means ①=output_a.)

Real and synthetic win-rates are NEVER merged into one rendered number: GateResult exposes
`real_delta` and `synthetic_delta` as separate fields and NO combined delta field. Combined
holdout counts exist only inside the pass decision for thresholds 1-3 (and are hard-bounded
by the threshold-4 real floor) and for the evidence-tier LABEL — never rendered as a win-rate.
"""
from __future__ import annotations

import hashlib
import logging
import statistics
from dataclasses import dataclass, field

from sqlalchemy import func, select

from server.db.models import Run, SyntheticTask
from server.services import binom, compare_judge, replay_run

logger = logging.getLogger(__name__)

DIMENSIONS = ("fabrication", "identity", "completion")

# ── thresholds (spec §E4; user-locked 60% / holdout N>=10) ───────────────────────────
MAX_PROMPT_LEN = 12000
LENGTH_MULT = 1.25
MIN_HOLDOUT_N = 10
WIN_RATE_MIN = 0.60
REAL_FLOOR_MIN_N = 3
REAL_FLOOR_WINRATE = 0.50
VERBOSE_WARN = 1.5
VERBOSE_FAIL = 2.0
POSITION_SENSITIVE_MAX = 0.40

# Evidence-tier boundaries on the holdout total p-value (spec §E4 statistical honesty).
TIER_STRONG_P = 0.05
TIER_MEDIUM_P = 0.20

# Gate 8 (signed decision A): which spawn fields the router/matcher actually consume.
# VERIFIED 2026-07-11 against the code:
#   - server/orchestrator/router.py `_spawn_registry()` feeds the router LLM: name,
#     domain (domain_category[.domain_subcategory]), persona_role, capabilities.
#   - server/services/spawn_match_service.py `score_spawns()` reads: domain_category /
#     domain_subcategory (structural) and capabilities (LLM coverage).
# NEITHER reads `system_prompt`. So an evolution diff that only rewrites system_prompt does
# NOT touch a routing-consumed field → gate 8 is skipped and the 3 compare dims stand.
ROUTING_CONSUMED_FIELDS = frozenset(
    {"name", "domain_category", "domain_subcategory", "persona_role", "capabilities"}
)

REPLAY_CONVERSATION_ID = replay_run.REPLAY_CONVERSATION_ID


class HoldoutViolation(RuntimeError):
    """Raised when a user-facing win-rate would be computed from a NON-holdout pair.

    This is the code-level enforcement of the holdout discipline (spec acceptance c): the
    only path to a rendered delta is `compute_delta`, which refuses any pair whose
    split_side != 'holdout'. Propose pairs may drive `internal_signal()` and nothing else."""


# ── pair-level win/loss/tie bookkeeping ──────────────────────────────────────────────

def _tally(pairs: list[dict], key: str = "overall") -> tuple[int, int, int]:
    """(wins, losses, ties) over `pairs` on `key` — 'b'=candidate win, 'a'=loss, else tie."""
    wins = losses = ties = 0
    for p in pairs:
        v = (p.get("per_dim", {}).get(key) if key != "overall" else p.get("overall")) or "tie"
        if v == "b":
            wins += 1
        elif v == "a":
            losses += 1
        else:
            ties += 1
    return wins, losses, ties


def _delta(pairs: list[dict], *, enforce_holdout: bool) -> dict:
    """Win/loss/tie + win-rate + exact p-value + Wilson CI over `pairs`.

    enforce_holdout=True (every user-facing delta) raises HoldoutViolation on any pair
    whose split_side != 'holdout'. enforce_holdout=False is ONLY for the propose-set
    internal signal, which is never rendered."""
    if enforce_holdout:
        for p in pairs:
            if p.get("split_side") != "holdout":
                raise HoldoutViolation(
                    "refusing to compute a user-facing delta from a "
                    f"{p.get('split_side')!r} pair (task_hash={p.get('task_hash')})"
                )
    wins, losses, ties = _tally(pairs)
    n = wins + losses
    win_rate = wins / n if n else 0.0
    lo, hi = binom.wilson_ci95(wins, n)
    return {
        "wins": wins, "losses": losses, "ties": ties, "n": n,
        "win_rate": win_rate, "p_value": binom.p_value(wins, n), "ci95": [lo, hi],
    }


def compute_delta(pairs: list[dict]) -> dict:
    """Public, holdout-ENFORCED delta. Feeding propose pairs here raises HoldoutViolation."""
    return _delta(pairs, enforce_holdout=True)


def _empty_delta() -> dict:
    return {"wins": 0, "losses": 0, "ties": 0, "n": 0,
            "win_rate": 0.0, "p_value": 1.0, "ci95": [0.0, 0.0]}


def _tier(p: float) -> str:
    if p < TIER_STRONG_P:
        return "strong"
    if p <= TIER_MEDIUM_P:
        return "medium"
    return "weak"


# ── GateResult ───────────────────────────────────────────────────────────────────────

@dataclass
class GateResult:
    """The gate verdict. real_delta and synthetic_delta are the ONLY win-rate deltas —
    there is deliberately NO combined/merged delta field (spec acceptance b)."""

    passed: bool
    reason: str
    flags: list[str]
    real_delta: dict
    synthetic_delta: dict
    evidence_tier: str          # 'strong' | 'medium' | 'weak' (by holdout total p)
    pairs: list[dict]           # holdout pair evidence (each row is trace-linkable)
    excluded_count: int         # replayable-corpus exclusions (non-replayable runs)
    protected_run_ids: list[int]
    # PROPOSE-set pairs — NOT user-facing; drive only internal_signal(). Excluded from
    # user_facing() and from any rendered delta.
    propose_pairs: list[dict] = field(default_factory=list)

    def user_facing(self) -> dict:
        """The card payload — holdout-only. No propose data, no merged delta."""
        return {
            "passed": self.passed,
            "reason": self.reason,
            "flags": list(self.flags),
            "real_delta": dict(self.real_delta),
            "synthetic_delta": dict(self.synthetic_delta),
            "evidence_tier": self.evidence_tier,
            "pairs": [dict(p) for p in self.pairs],
            "excluded_count": self.excluded_count,
            "protected_run_ids": list(self.protected_run_ids),
        }

    def internal_signal(self) -> dict:
        """PROPOSE-set aggregate for the optimizer. Never rendered to the user."""
        return _delta(self.propose_pairs, enforce_holdout=False)


# ── corpus assembly ──────────────────────────────────────────────────────────────────

def _split_side(spawn_id: int, task: str) -> str:
    """Deterministic propose/holdout split for a REAL task (~40% holdout). Same
    (spawn_id, task) always maps to the same side — no RNG, no recency skew."""
    h = hashlib.sha256(f"{spawn_id}::{task}".encode("utf-8")).hexdigest()
    return "holdout" if (int(h[:8], 16) % 5) < 2 else "propose"


class Corpus(list):
    """A list[pairtask] that also carries `.excluded` — the count of runs build_corpus
    dropped as non-replayable — so a caller can surface it without a second DB pass while
    the value still satisfies the spec's list[pairtask] return type."""

    excluded: int = 0


async def build_corpus(db, spawn_id: int, *, baseline_started_at=None) -> Corpus:
    """Assemble the paired corpus for `spawn_id`.

    real: clean-corpus live runs (kind='live', epoch>=1, status='scored', created_at >=
    baseline_started_at when set) that ARE hermetically replayable; split by deterministic
    (spawn_id, task) hash. synthetic: the CURRENT-version active SyntheticTasks, using their
    STORED split_side (a holdout task's variant can never leak into propose — spec CRITICAL-8).

    Each pairtask: {task, corpus_label:'real'|'synthetic', source_ref, split_side}. The
    number of runs dropped as non-replayable is on the returned Corpus's `.excluded`."""
    pairs: Corpus = Corpus()
    excluded = 0

    q = select(Run).where(
        Run.spawn_id == spawn_id, Run.kind == "live", Run.epoch >= 1,
        Run.status == "scored",
    )
    if baseline_started_at is not None:
        q = q.where(Run.created_at >= baseline_started_at)
    runs = (await db.execute(q.order_by(Run.id.desc()))).scalars().all()
    for run in runs:
        if not await replay_run.is_replayable(db, run.id):
            excluded += 1
            continue
        task = run.user_message or ""
        if not task:
            continue
        pairs.append({
            "task": task, "corpus_label": "real", "source_ref": run.id,
            "split_side": _split_side(spawn_id, task),
        })

    ver = (await db.execute(
        select(func.max(SyntheticTask.version)).where(SyntheticTask.spawn_id == spawn_id)
    )).scalar()
    if ver is not None:
        srows = (await db.execute(
            select(SyntheticTask).where(
                SyntheticTask.spawn_id == spawn_id,
                SyntheticTask.version == ver,
                SyntheticTask.status == "active",
            )
        )).scalars().all()
        for st in srows:
            pairs.append({
                "task": st.task, "corpus_label": "synthetic",
                "source_ref": {"synth_id": st.id, "version": st.version},
                "split_side": st.split_side,
            })

    pairs.excluded = excluded
    return pairs


# ── the gate ─────────────────────────────────────────────────────────────────────────

def routing_triggered(changed_fields) -> bool:
    """Whether a diff over `changed_fields` touches a router/matcher-consumed field
    (gate 8). A system_prompt-only evolution diff → False (routing not consumed)."""
    return bool(ROUTING_CONSUMED_FIELDS & set(changed_fields or ()))


def _fail_prerun(reason: str) -> GateResult:
    return GateResult(
        passed=False, reason=reason, flags=[],
        real_delta=_empty_delta(), synthetic_delta=_empty_delta(),
        evidence_tier="weak", pairs=[], excluded_count=0, protected_run_ids=[],
        propose_pairs=[],
    )


async def run_gate(db, *, spawn_id: int, candidate_prompt: str, baseline_prompt: str,
                   corpus: list[dict], persona: str = "", changed_fields=None,
                   excluded: int = 0) -> GateResult:
    """Replay every pair (baseline arm A vs candidate arm B on one shared ambient), judge it,
    and apply the holdout thresholds. Returns a GateResult. `corpus` is a list of pairtasks
    {task, corpus_label, source_ref, split_side}."""
    # Threshold 5 — length cap, BEFORE any judge call (saves cost on a bloated candidate).
    if len(candidate_prompt) > len(baseline_prompt) * LENGTH_MULT or \
            len(candidate_prompt) > MAX_PROMPT_LEN:
        return _fail_prerun("length_cap")

    flags: list[str] = []
    pairs: list[dict] = []
    for pt in corpus:
        ambient = await replay_run.snapshot_ambient(
            db, spawn_id=spawn_id, conversation_id=REPLAY_CONVERSATION_ID, task=pt["task"])
        base = await replay_run.run_arm(
            db, spawn_id=spawn_id, task=pt["task"], system_prompt=baseline_prompt,
            ambient=ambient)
        cand = await replay_run.run_arm(
            db, spawn_id=spawn_id, task=pt["task"], system_prompt=candidate_prompt,
            ambient=ambient)
        verdict = await compare_judge.compare(
            task=pt["task"], persona=persona,
            output_a=base.get("output", ""), output_b=cand.get("output", ""),
            evidence_a=base.get("evidence", ""), evidence_b=cand.get("evidence", ""),
            item=pt,
        )
        pairs.append({
            "task_hash": _task_hash(spawn_id, pt["task"]),
            "corpus_label": pt["corpus_label"],
            "source_ref": pt.get("source_ref"),
            "split_side": pt["split_side"],
            "baseline_run_id": base.get("run_id"),
            "candidate_run_id": cand.get("run_id"),
            "base_out_len": len(base.get("output", "") or ""),
            "cand_out_len": len(cand.get("output", "") or ""),
            "per_dim": {d: (verdict.get("dimensions") or {}).get(d, "tie") for d in DIMENSIONS},
            "overall": verdict.get("overall", "tie"),
            "position_sensitive": bool(verdict.get("position_sensitive", False)),
        })

    holdout = [p for p in pairs if p["split_side"] == "holdout"]
    propose = [p for p in pairs if p["split_side"] == "propose"]
    real_holdout = [p for p in holdout if p["corpus_label"] == "real"]
    synth_holdout = [p for p in holdout if p["corpus_label"] == "synthetic"]

    real_delta = compute_delta(real_holdout)
    synthetic_delta = compute_delta(synth_holdout)

    # Combined HOLDOUT counts — internal only (thresholds 1-3 pass decision + tier label).
    h_wins, h_losses, _ = _tally(holdout)
    h_n = h_wins + h_losses
    tier = _tier(binom.p_value(h_wins, h_n))

    protected = [p["baseline_run_id"] for p in pairs] + [p["candidate_run_id"] for p in pairs]
    protected = [r for r in protected if r is not None]

    reason: str | None = None
    # Threshold 1 — holdout non-tie N >= 10.
    if h_n < MIN_HOLDOUT_N:
        reason = "insufficient_holdout"
    # Threshold 2 — holdout non-tie win-rate >= 60%.
    elif (h_wins / h_n) < WIN_RATE_MIN:
        reason = "holdout_winrate"
    else:
        # Threshold 3 — per-dimension wins >= losses (no dim regresses).
        for d in DIMENSIONS:
            dw, dl, _ = _tally(holdout, key=d)
            if dw < dl:
                reason = f"dim_regressed:{d}"
                break

    # Threshold 4 — the REAL floor (spec CRITICAL-3): synthetic wins cannot carry a real
    # regression. Only evaluated if nothing above already failed.
    if reason is None:
        if real_delta["n"] >= REAL_FLOOR_MIN_N:
            real_dims_ok = True
            for d in DIMENSIONS:
                rw, rl, _ = _tally(real_holdout, key=d)
                if rl > rw:
                    real_dims_ok = False
                    break
            if real_delta["win_rate"] < REAL_FLOOR_WINRATE or not real_dims_ok:
                reason = "real_floor"
        else:
            flags.append("synthetic_driven")

    # Threshold 6 — output verbosity (median candidate/baseline output-length ratio on holdout).
    ratios = [p["cand_out_len"] / p["base_out_len"] for p in holdout if p["base_out_len"] > 0]
    if ratios:
        med = statistics.median(ratios)
        if med > VERBOSE_FAIL:
            if reason is None:
                reason = "verbose_fail"
        elif med > VERBOSE_WARN:
            flags.append("verbose_warn")

    # Threshold 7 — position-sensitivity fraction (low-confidence warn on the card).
    if holdout:
        ps_frac = sum(1 for p in holdout if p["position_sensitive"]) / len(holdout)
        if ps_frac > POSITION_SENSITIVE_MAX:
            flags.append("low_confidence")

    # Threshold 8 — routing trigger (signed decision A). A system_prompt-only diff does not
    # touch a routing-consumed field, so this is skipped for the evolution loop. If a future
    # caller diffs routing metadata, run_gate has no spawn-metadata to re-run the router with,
    # so it flags the gap conservatively rather than silently passing.
    if changed_fields is None:
        changed_fields = frozenset({"system_prompt"})
    if routing_triggered(changed_fields):
        flags.append("routing_uncheckable")

    return GateResult(
        passed=(reason is None),
        reason=reason or "pass",
        flags=flags,
        real_delta=real_delta,
        synthetic_delta=synthetic_delta,
        evidence_tier=tier,
        pairs=holdout,
        excluded_count=excluded or getattr(corpus, "excluded", 0),
        protected_run_ids=protected,
        propose_pairs=propose,
    )


def _task_hash(spawn_id: int, task: str) -> str:
    return hashlib.sha256(f"{spawn_id}::{task}".encode("utf-8")).hexdigest()[:16]


def recompute_verdict(holdout_pairs: list[dict]) -> dict:
    """Re-apply thresholds 1-4 to an ALREADY-ASSEMBLED holdout pair list — the living
    proposal's accumulation path (spec §E4 / decision B.2). Given the union of a proposal's
    stored holdout pairs and freshly replayed ones, recompute the pass decision, the split
    real/synthetic deltas, the evidence tier, and any real-floor flag.

    Mirrors run_gate's threshold 1-4 math exactly (it reuses the same _tally/_delta/_tier
    helpers and the module thresholds) but takes pairs directly instead of replaying — so a
    refresh never re-runs the arms it already has. compute_delta still enforces that every
    pair is a holdout pair (a propose pair here raises HoldoutViolation)."""
    real_holdout = [p for p in holdout_pairs if p.get("corpus_label") == "real"]
    synth_holdout = [p for p in holdout_pairs if p.get("corpus_label") == "synthetic"]
    real_delta = compute_delta(real_holdout)
    synthetic_delta = compute_delta(synth_holdout)

    h_wins, h_losses, _ = _tally(holdout_pairs)
    h_n = h_wins + h_losses
    tier = _tier(binom.p_value(h_wins, h_n))

    flags: list[str] = []
    reason: str | None = None
    if h_n < MIN_HOLDOUT_N:
        reason = "insufficient_holdout"
    elif (h_wins / h_n) < WIN_RATE_MIN:
        reason = "holdout_winrate"
    else:
        for d in DIMENSIONS:
            dw, dl, _ = _tally(holdout_pairs, key=d)
            if dw < dl:
                reason = f"dim_regressed:{d}"
                break

    if reason is None:
        if real_delta["n"] >= REAL_FLOOR_MIN_N:
            real_dims_ok = True
            for d in DIMENSIONS:
                rw, rl, _ = _tally(real_holdout, key=d)
                if rl > rw:
                    real_dims_ok = False
                    break
            if real_delta["win_rate"] < REAL_FLOOR_WINRATE or not real_dims_ok:
                reason = "real_floor"
        else:
            flags.append("synthetic_driven")

    return {
        "passed": reason is None,
        "reason": reason or "pass",
        "flags": flags,
        "real_delta": real_delta,
        "synthetic_delta": synthetic_delta,
        "evidence_tier": tier,
    }
