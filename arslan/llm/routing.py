"""Deterministic, zero-LLM-call role -> provider routing over the model catalog."""
from __future__ import annotations

from arslan.llm.catalog import CAPABILITY_DIMENSIONS, capabilities_for, language_fit

# "judge" (run_eval_service/compare_judge) and "judgment" (optimizer) are pinned here
# (E1): evaluation/optimization must ALWAYS run on the primary config — never drift to
# a cheaper model under strategy routing.
JUDGMENT_ROLES = frozenset({"router", "converse", "critical", "judge", "judgment"})
# WORKER_ROLES is illustrative/documentation only — not used in routing logic.
# It documents the intended set of worker roles that ARE eligible for
# strategy-based routing (i.e. roles NOT in JUDGMENT_ROLES).
# Do not delete: preserves intent for future callers and audits.
WORKER_ROLES = frozenset({"execute", "summarize", "draft"})

STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "cost":        {"cost": 5, "speed": 2, "tool_calling": 1, "reasoning": 1, "long_context": 1, "language_fit": 2},
    "balanced":    {"cost": 2, "speed": 2, "tool_calling": 2, "reasoning": 2, "long_context": 2, "language_fit": 2},
    "performance": {"cost": 0, "speed": 1, "tool_calling": 3, "reasoning": 3, "long_context": 2, "language_fit": 2},
}
QUALITY_WEIGHTS = {"cost": 0, "speed": 1, "tool_calling": 3, "reasoning": 4, "long_context": 2, "language_fit": 2}


def _primary(configs: list[dict]) -> dict | None:
    if not configs:
        return None
    return next((c for c in configs if c.get("is_primary")), configs[0])


def _score(provider: str, weights: dict[str, float], language: str | None) -> float:
    caps = capabilities_for(provider)
    total = sum(weights.get(dim, 0) * caps.get(dim, 5) for dim in CAPABILITY_DIMENSIONS)
    total += weights.get("language_fit", 0) * language_fit(provider, language)
    return total


def _best(configs: list[dict], weights: dict[str, float], language: str | None) -> dict | None:
    """Highest score wins; a TIE goes to the user's primary, not to insertion order.

    🔴 `>` alone made two configs on the same provider score identically and kept
    whichever had the lower id — so the primary the user explicitly chose lost to a
    row that happened to be created first, silently, because both answers look
    plausible.
    """
    best, best_score = None, float("-inf")
    for c in configs:
        s = _score(c["provider"], weights, language)
        if s > best_score or (s == best_score and c.get("is_primary")
                              and not (best or {}).get("is_primary")):
            best, best_score = c, s
    return best


def usable(c: dict) -> bool:
    """Can this config possibly answer?

    Filtered, not down-weighted. A weight says "worse"; these are ZERO — a low weight
    still wins when everything else is worse, and the request is then guaranteed to
    fail. Two ways to be unusable:

    * the key cannot be decrypted, or was never entered (spec ⓪'s vocabulary). The
      adapter would be handed an empty string and the provider would answer 401,
      which points the user at the provider rather than at their key.
    * a health probe has actually SEEN it fail.

    ``healthy is None`` means no probe has run, and that counts as usable: treating
    unknown as dead would stop a fresh install with no probe history from routing at
    all. Fail-open on the propose side is the standing rule.
    """
    if c.get("key_state") in ("unset", "undecryptable"):
        return False
    return c.get("healthy") is not False


def select(role: str, strategy: str, configs: list[dict], language: str | None) -> dict | None:
    primary = _primary(configs)
    if strategy == "single" or role in JUDGMENT_ROLES or len(configs) < 2:
        return primary
    weights = STRATEGY_WEIGHTS.get(strategy, STRATEGY_WEIGHTS["balanced"])
    # When NOTHING is usable this yields no candidate, and the trailing `or primary`
    # answers with the user's own choice. That is better than the `or configs` this
    # used to have: among configs that all cannot work, a score is meaningless, and
    # falling back to the highest-scoring DEAD one rather than the chosen one is worse
    # for no reason. A mutation removing `or configs` failed nothing, which is how the
    # redundancy showed up — the clause was not earning its place.
    #
    # What must NOT happen is returning nothing at all: refusing to answer because no
    # config looks healthy would turn a stale health probe into an outage. The request
    # may still fail, but then it fails at the provider with a real error.
    candidates = [c for c in configs if usable(c)]
    return _best(candidates, weights, language) or primary


def suggest_primary(configs: list[dict], language: str | None) -> dict | None:
    return _best(configs, QUALITY_WEIGHTS, language)
