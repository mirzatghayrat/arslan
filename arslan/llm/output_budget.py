"""Per-endpoint output budgets (0.1.49 P1.2, design section 5.1).

`initial` is what every request declares; `ceiling` is the most a request may
be raised to after a finish_reason == "length" cut. Thinking models spend the
same max_tokens on reasoning AND the answer (S10 probe: a 64-token cap was cut
inside the reasoning), so a flat 8192 truncated real work (kernel sample, T5).

The 8192 default is not arbitrary for aggregators: OpenRouter reserves the
declared max_tokens against the key's credit and refuses a key that cannot
cover it (v0.1.25 field report), so it keeps the small opening budget and is
only raised when a response was actually cut.
"""
from __future__ import annotations

from dataclasses import dataclass

DEEPSEEK_BASES = {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
DEEPSEEK_MODELS = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro"}


@dataclass(frozen=True)
class OutputBudget:
    initial: int
    ceiling: int


def for_endpoint(base_url: str, model: str) -> OutputBudget:
    base = (base_url or "").rstrip("/")
    if base in DEEPSEEK_BASES and model in DEEPSEEK_MODELS:
        # Official max output 384K; billed per generated token, nothing reserved.
        return OutputBudget(initial=32_768, ceiling=131_072)
    if "openrouter.ai" in base:
        return OutputBudget(initial=8_192, ceiling=32_768)
    return OutputBudget(initial=8_192, ceiling=16_384)
