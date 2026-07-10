"""Exact small-sample binomial statistics for the ReplayGate (S2 E4).

Two pure functions, no LLM, no DB:

- p_value(wins, n): one-sided EXACT binomial test against H0 p=0.5 —
      P(X >= wins) = sum_{k=wins..n} C(n,k) * 0.5**n
  the probability of seeing at least `wins` candidate-wins out of `n` non-tie
  pairs if the candidate were no better than the baseline. Small library ⇒ we
  do NOT approximate; math.comb is exact.
- wilson_ci95(wins, n): the Wilson score 95% interval for the win-rate, which
  behaves well at the small n and extreme rates this gate lives in (unlike the
  naive normal interval that runs off [0,1]).

Both are total: n<=0 returns the safe "no evidence" answer (p=1.0, CI=(0,0))
rather than raising, and wins is clamped into [0, n].
"""
from __future__ import annotations

import math

# 97.5th percentile of the standard normal — the z for a two-sided 95% (⇒ Wilson) interval.
_Z95 = 1.959963984540054


def p_value(wins: int, n: int) -> float:
    """One-sided exact binomial p-value, H0: p=0.5. n<=0 → 1.0 (no evidence)."""
    if n <= 0:
        return 1.0
    w = max(0, min(int(wins), n))
    tail = sum(math.comb(n, k) for k in range(w, n + 1))
    return tail * (0.5 ** n)


def wilson_ci95(wins: int, n: int) -> tuple[float, float]:
    """Wilson score 95% CI for the win-rate. n<=0 → (0.0, 0.0)."""
    if n <= 0:
        return (0.0, 0.0)
    w = max(0, min(int(wins), n))
    phat = w / n
    z2 = _Z95 * _Z95
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2 * n)) / denom
    half = (_Z95 * math.sqrt(phat * (1.0 - phat) / n + z2 / (4 * n * n))) / denom
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return (lo, hi)
