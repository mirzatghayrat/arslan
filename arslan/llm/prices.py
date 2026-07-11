"""Static USD price table for known model ids + honest conversion helpers.

MAINTENANCE: updated per release, by hand. Source = the providers' official
pricing pages, verified 2026-07-11 (spec 2026-07-11-provider-catalog-local-models-design.md
Part A2). This module NEVER fetches prices over the network (decision D4) — the
OpenRouter dynamic price overlay ships with the Provider round's dynamic catalog.

Honesty rule: an unknown model, or missing token counts, yields None — the UI
then shows tokens without a USD figure. We never guess a price.

Known coarseness: prefix matching prices unknown subfamily variants at the parent
rate (a future "gpt-5.6-terra-lite" would bill as -terra) until the dynamic
catalog overlay ships in the Provider round.
"""
from __future__ import annotations

# Key = model-id PREFIX (longest prefix wins, so versioned ids like
# "gpt-5.6-terra-2026xx" resolve to their family entry).
# Value = (usd_per_mtok_in, usd_per_mtok_out).
PRICES: dict[str, tuple[float, float]] = {
    # Anthropic — official pricing page, verified 2026-07-11.
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    # OpenAI — official pricing page, verified 2026-07-11.
    "gpt-5.6-sol": (5.0, 30.0),
    "gpt-5.6-terra": (2.5, 15.0),
    "gpt-5.6-luna": (1.0, 6.0),
    # DeepSeek — official pricing page, verified 2026-07-11.
    "deepseek-v4-pro": (0.44, 0.87),
    "deepseek-v4-flash": (0.14, 0.28),
    # Google Gemini — official pricing page, verified 2026-07-11.
    "gemini-3.5-flash": (1.5, 9.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
    # Mistral — 二手来源,发版复核 (secondary sources; re-verify at release).
    "mistral-medium-2604": (2.0, 5.0),
    "mistral-large-2512": (0.5, 1.5),
    "mistral-small-2603": (0.15, 0.60),
    # Qwen (DashScope international) — 二手来源,发版复核.
    # qwen3.7-max: LIST price; a 1.25/3.75 promo exists — we deliberately use LIST.
    "qwen3.7-max": (2.5, 7.5),
    "qwen3.7-plus": (0.40, 1.20),
    "qwen3.6-flash": (0.05, 0.20),
}

# Local models (ollama seed tags) — genuinely free, but ONLY as local calls.
# Review I1: these very ids exist as PAID hosted models on BYOK OpenAI-compat
# clouds (DashScope serves deepseek-r1), so $0 is gated on provider == "ollama"
# (the sole local provider today; custom/local providers get honest None until
# the Provider round's dynamic catalog).
LOCAL_PRICES: dict[str, tuple[float, float]] = {
    "llama3.1": (0.0, 0.0),
    "qwen3.5": (0.0, 0.0),
    "gemma4": (0.0, 0.0),
    "deepseek-r1": (0.0, 0.0),
}


def usd(
    model: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
    *,
    provider: str | None = None,
) -> float | None:
    """USD cost for a call, or None when it can't be known honestly.

    None model / no prefix match / either token count None → None (never guess).
    Longest-prefix match: "gpt-5.6-terra-2026xx" hits "gpt-5.6-terra", not any
    shorter overlapping prefix.
    Provider gate (review I1): provider == "ollama" prices against LOCAL_PRICES
    ONLY (local calls are free, and never billed at cloud rates); every other
    provider — including None — prices against the cloud table only, so a hosted
    "deepseek-r1" is honestly unpriced instead of labelled free.
    """
    if model is None or tokens_in is None or tokens_out is None:
        return None
    # Tables are read at call time (not captured at import) so tests can patch them.
    table = LOCAL_PRICES if provider == "ollama" else PRICES
    match: tuple[float, float] | None = None
    match_len = -1
    for prefix, pair in table.items():
        if len(prefix) > match_len and model.startswith(prefix):
            match, match_len = pair, len(prefix)
    if match is None:
        return None
    per_in, per_out = match
    return tokens_in / 1_000_000 * per_in + tokens_out / 1_000_000 * per_out


def fmt_usd(v: float | None) -> str | None:
    """Display form: None → None; exactly 0 → "$0.0000" (local models really cost
    nothing — "<$0.0001" would dishonestly claim a cost); positive but below the
    4-decimal display floor → "<$0.0001"; else 4 decimal places."""
    if v is None:
        return None
    if v == 0.0:
        return "$0.0000"
    if v < 0.0001:
        return "<$0.0001"
    return f"${v:.4f}"
