"""Deterministic, zero-LLM-call role -> provider routing over the model catalog."""
from __future__ import annotations

from arslan.llm.catalog import CAPABILITY_DIMENSIONS, capabilities_for, language_fit

JUDGMENT_ROLES = frozenset({"router", "converse", "critical"})
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
    best, best_score = None, float("-inf")
    for c in configs:
        s = _score(c["provider"], weights, language)
        if s > best_score:
            best, best_score = c, s
    return best


def select(role: str, strategy: str, configs: list[dict], language: str | None) -> dict | None:
    primary = _primary(configs)
    if strategy == "single" or role in JUDGMENT_ROLES or len(configs) < 2:
        return primary
    weights = STRATEGY_WEIGHTS.get(strategy, STRATEGY_WEIGHTS["balanced"])
    return _best(configs, weights, language) or primary


def suggest_primary(configs: list[dict], language: str | None) -> dict | None:
    return _best(configs, QUALITY_WEIGHTS, language)
