"""Per-endpoint output budgets (0.1.49 P1.2, design section 5.1).

`initial` is what every request declares; `ceiling` is the most a request may
be raised to after a finish_reason == "length" cut. Thinking models spend the
same max_tokens on reasoning AND the answer (S10 probe: a 64-token cap was cut
inside the reasoning), so a flat 8192 truncated real work (kernel sample, T5).

for_endpoint() is Claude's budget and official DeepSeek's (unchanged in v0.1.64).
v0.1.64: every other OpenAI-compatible key and Gemini declare the model's own
documented maximum output (for_model), as mainstream agents do, or 32,768 for
a model whose maximum is not known. An endpoint that refuses the declared cap
(a smaller model limit, or OpenRouter reserving it against a key's credit, the
v0.1.25 field report) is asked once more at 8,192 (output_fallback.py).
"""
from __future__ import annotations

import re
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


#: Each listed OpenAI and Gemini model's documented maximum output, from the vendor's model page (read
#: 2026-11-14): developers.openai.com/api/docs/models/<id> ("128,000 max output tokens") and
#: aistudio.google.com/docs/models/<id> ("Output token limit 65,536"). gemini-3.6-flash is where Google
#: routes gemini-3.5-flash. Never above the documented value: the API refuses a larger one.
DOCUMENTED_MAX_OUTPUT = {
    "gpt-5.6-sol": 128_000,
    "gpt-5.6-terra": 128_000,
    "gpt-5.6-luna": 128_000,
    "gemini-3.6-flash": 65_536,
    "gemini-3.5-flash": 65_536,
    "gemini-2.5-pro": 65_536,
    "gemini-2.5-flash": 65_536,
}
#: An unknown or custom model (any other id, on any OpenAI-compatible endpoint or Gemini).
UNKNOWN_MAX_OUTPUT = 32_768
#: What a request whose cap the endpoint refused is sent again with, once (output_fallback.py).
REFUSED_CAP_FALLBACK = 8_192

# OpenAI's reasoning families take `max_completion_tokens`; `max_tokens` is "not compatible with o-series
# models" and deprecated (Chat Completions API reference). A bare id only: OpenRouter's "openai/..." and
# other compatible servers keep `max_tokens`.
_COMPLETION_TOKENS_FAMILY = re.compile(r"(?:gpt-5|o[1-9])(?:[.\-].*)?")


def for_model(base_url: str, model: str) -> OutputBudget:
    """OpenAI-compatible and Gemini keys: the model's documented maximum, or UNKNOWN_MAX_OUTPUT. Official
    DeepSeek keeps for_endpoint(). The opening budget is the ceiling: a length cut is continued, not raised."""
    base = (base_url or "").rstrip("/")
    if base in DEEPSEEK_BASES and model in DEEPSEEK_MODELS:
        return for_endpoint(base_url, model)
    cap = DOCUMENTED_MAX_OUTPUT.get(model, UNKNOWN_MAX_OUTPUT)
    return OutputBudget(initial=cap, ceiling=cap)


def output_param(model: str) -> str:
    """The OpenAI-compatible body key that carries the output cap for `model`."""
    return "max_completion_tokens" if _COMPLETION_TOKENS_FAMILY.fullmatch(model or "") else "max_tokens"
