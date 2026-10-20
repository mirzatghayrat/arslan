"""Static USD price table for known model ids + honest conversion helpers.

MAINTENANCE: updated per release, by hand. Source = the providers' official
pricing pages, read 2026-10-20 for K4a (each row cites its page); first built
2026-07-11 (spec 2026-07-11-provider-catalog-local-models-design.md Part A2). This module NEVER fetches prices over the network (decision D4) — the
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
    # K4a refresh: every row below cites its official page, read 2026-10-20 (⓪Plan's condition: a number
    # that can't be confirmed there stays out, and that model is unpriced).
    # Anthropic — https://platform.claude.com/docs/en/about-claude/pricing (read 2026-10-20). "Claude 4.6
    # and later models (except Claude Haiku 5.5) ... include the full 1M token context window at standard
    # pricing" — Haiku 5.5's prompts over 100,000 tokens are in LONG_PROMPT_PRICES.
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),           # "the $2/$10 launch price ... is now the standard price"
    "claude-haiku-5-5": (0.10, 0.50),         # prompts up to 100,000 tokens
    "claude-haiku-4-5": (1.0, 5.0),
    # OpenAI — https://developers.openai.com/api/docs/pricing (read 2026-10-20), Standard, ≤272K input
    # tokens (longer: LONG_PROMPT_PRICES). "GPT-5.6 Sol's promotional pricing is available at least through
    # November 21, 2026": re-verify after that date.
    "gpt-5.6-sol": (4.0, 20.0),
    "gpt-5.6-terra": (2.0, 12.0),
    "gpt-5.6-luna": (0.20, 1.20),
    # DeepSeek — https://api-docs.deepseek.com/quick_start/pricing (read 2026-10-20), PEAK prices; "Off-peak
    # rates are half of the peak rates" (OFF_PEAK_HALF). "The legacy names deepseek-v4-flash ... are billed
    # at the Flash price." deepseek-chat / deepseek-reasoner are not on the page: unpriced.
    "deepseek-v4-pro": (1.32, 3.96),
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4-flash": (0.30, 1.20),
    # Google Gemini — https://ai.google.dev/gemini-api/docs/pricing (read 2026-10-20), Paid Tier Standard,
    # text/image/video input (audio is priced higher and isn't told apart here). gemini-3.5-flash has no
    # price on the page (it routes to gemini-3.6-flash): unpriced. Context-cache storage is billed per hour,
    # not per token, and isn't included.
    "gemini-2.5-pro": (1.25, 10.0),           # prompts ≤ 200k tokens (longer: LONG_PROMPT_PRICES)
    "gemini-2.5-flash": (0.30, 2.50),
    # Mistral and Qwen rows came from secondary sources (2026-07-11). K4a (⓪Plan, condition (a)): unpriced —
    # token cap only — until someone checks them against the providers' official pages.
}

# Local models (ollama seed tags) — genuinely free, but ONLY as local calls.
# Review I1: these very ids exist as PAID hosted models on BYOK OpenAI-compat
# clouds (DashScope serves deepseek-r1), so $0 is gated on provider == "ollama"
# (the sole local provider today; custom/local providers get honest None until
# the Provider round's dynamic catalog).
# Kept as documentation of the ollama seed tags; usd() no longer consults it —
# provider == "ollama" is $0 for any tag (no per-token billing in the protocol).
LOCAL_PRICES: dict[str, tuple[float, float]] = {
    "llama3.1": (0.0, 0.0),
    "qwen3.5": (0.0, 0.0),
    "gemma4": (0.0, 0.0),
    "deepseek-r1": (0.0, 0.0),
}


# K4a (v0.1.63): cache prices per model prefix, USD per million tokens: (cache read, cache write with a
# 5-minute life, cache write with a 1-hour life). None = not billed separately (a provider with no cache
# writes). A model in PRICES whose cache tokens show up without a row here is unpriced (usd_for_usage
# returns None), never priced as plain input. Rows only from the official pages (⓪Plan's condition: each
# cites its page and the date read).
CACHE_PRICES: dict[str, tuple[float | None, float | None, float | None]] = {
    # Anthropic (same page): "Cache hits and refreshes", "5m cache writes", "1h cache writes".
    "claude-fable-5-1": (0.25, 12.50, 20.0),
    "claude-fable-5": (1.0, 12.50, 20.0),
    "claude-opus-5-5": (0.20, 5.0, 8.0),
    "claude-opus-5": (0.50, 6.25, 10.0),
    "claude-opus-4-8": (0.50, 6.25, 10.0),
    "claude-sonnet-5-5": (0.10, 2.50, 4.0),
    "claude-sonnet-5": (0.20, 2.50, 4.0),
    "claude-haiku-5-5": (0.01, 0.125, 0.20),
    "claude-haiku-4-5": (0.10, 1.25, 2.0),
    # OpenAI (same page): "Cached input". Its "Cache writes" price isn't used: the usage read here doesn't
    # tell a written input token from a plain one, so written tokens are priced as input (25% under).
    "gpt-5.6-sol": (0.40, None, None),
    "gpt-5.6-terra": (0.20, None, None),
    "gpt-5.6-luna": (0.02, None, None),
    # DeepSeek (same page): "1M INPUT TOKENS (CACHE HIT)", peak.
    "deepseek-v4-pro": (0.044, None, None),
    "deepseek-flash": (0.006, None, None),
    "deepseek-v4-flash": (0.006, None, None),
    # Gemini (same page): "Context caching price", per token.
    "gemini-2.5-pro": (0.125, None, None),
    "gemini-2.5-flash": (0.03, None, None),
}
# A request whose whole input (cache reads and writes included) is over the threshold pays these prices
# for all its tokens: (threshold, (input, output), (cache read, write 5m, write 1h)). Same pages and date.
LONG_PROMPT_PRICES: dict[str, tuple[int, tuple[float, float], tuple[float | None, float | None, float | None]]] = {
    # "A request's prompt length counts all of its input tokens, including cache reads and cache writes."
    "claude-haiku-5-5": (100_000, (0.50, 2.50), (0.05, 0.625, 1.0)),
    "gpt-5.6-sol": (272_000, (8.0, 30.0), (0.80, None, None)),
    "gpt-5.6-terra": (272_000, (4.0, 18.0), (0.40, None, None)),
    "gpt-5.6-luna": (272_000, (0.40, 1.80), (0.04, None, None)),
    "gemini-2.5-pro": (200_000, (2.50, 15.0), (0.25, None, None)),
}
# DeepSeek: "Off-peak rates are half of the peak rates. Peak hours are 01:00 - 04:00 and 06:00 - 10:00 UTC,
# Monday through Friday, excluding Chinese public holidays." Holidays aren't modelled: inside those hours
# they price at peak, which overstates.
OFF_PEAK_HALF: tuple[str, ...] = ("deepseek-",)


def _row(table: dict, model: str):
    match, match_len = None, -1
    for prefix, row in table.items():
        if len(prefix) > match_len and model.startswith(prefix):
            match, match_len = row, len(prefix)
    return match


def _int(value) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _off_peak(now) -> bool:
    if now.weekday() >= 5:
        return True
    return not (1 <= now.hour < 4 or 6 <= now.hour < 10)


def _input_total(u: dict) -> int | None:
    """The whole input of one response, cache included, in whatever shape the provider reports it."""
    hit, miss = _int(u.get("prompt_cache_hit_tokens")), _int(u.get("prompt_cache_miss_tokens"))
    if hit is not None and miss is not None:
        return hit + miss
    for key in ("prompt_tokens", "promptTokenCount"):
        if _int(u.get(key)) is not None:
            return u[key]
    if _int(u.get("input_tokens")) is not None:
        return (u["input_tokens"] + (_int(u.get("cache_read_input_tokens")) or 0)
                + (_int(u.get("cache_creation_input_tokens")) or 0))
    return None


def usd_for_usage(model: str | None, usage: dict | None, *, provider: str | None = None,
                  long_cache: bool = False, now=None) -> float | None:
    """USD for one response from its real usage, by cache tier (K4a): uncached input, cache read, cache
    write (5 minutes or 1 hour) and output each at its own price. None when it can't be known honestly:
    no model, no price, no real usage (an estimate), or cache tokens with no confirmed cache price.
    Anthropic writes without a 5m/1h split are priced at the hour's rate when the request asked for the
    long cache (K3), else at the 5 minutes' rate. ollama is free."""
    u = usage or {}
    if provider == "ollama":
        return 0.0
    if model is None:
        return None
    base = _row(PRICES, model)
    if base is None:
        return None
    per_in, per_out = base
    read_p, write5_p, write1_p = _row(CACHE_PRICES, model) or (None, None, None)
    long = _row(LONG_PROMPT_PRICES, model)
    whole = _input_total(u)
    if long is not None and whole is not None and whole > long[0]:
        (per_in, per_out), (read_p, write5_p, write1_p) = long[1], long[2]
    parts: list[tuple[int, float | None]] = []
    hit, miss = _int(u.get("prompt_cache_hit_tokens")), _int(u.get("prompt_cache_miss_tokens"))
    out = _int(u.get("completion_tokens"))
    details = u.get("prompt_tokens_details") if isinstance(u.get("prompt_tokens_details"), dict) else {}
    cached, prompt = _int(details.get("cached_tokens")), _int(u.get("prompt_tokens"))
    a_in, a_out = _int(u.get("input_tokens")), _int(u.get("output_tokens"))
    g_prompt, g_out = _int(u.get("promptTokenCount")), _int(u.get("candidatesTokenCount"))
    if hit is not None and miss is not None and out is not None:                   # DeepSeek
        parts = [(miss, per_in), (hit, read_p), (out, per_out)]
    elif prompt is not None and out is not None:                                    # OpenAI-compatible
        cached = cached or 0
        parts = [(prompt - cached, per_in), (cached, read_p), (out, per_out)]
    elif a_in is not None and a_out is not None:                                    # Anthropic
        read = _int(u.get("cache_read_input_tokens")) or 0
        written = _int(u.get("cache_creation_input_tokens")) or 0
        split = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
        w5, w1 = _int(split.get("ephemeral_5m_input_tokens")), _int(split.get("ephemeral_1h_input_tokens"))
        if w5 is None and w1 is None:
            w5, w1 = (0, written) if long_cache else (written, 0)
        parts = [(a_in, per_in), (read, read_p), (w5 or 0, write5_p), (w1 or 0, write1_p), (a_out, per_out)]
    elif g_prompt is not None and g_out is not None:                                # Gemini
        g_cached = _int(u.get("cachedContentTokenCount")) or 0
        thoughts = _int(u.get("thoughtsTokenCount")) or 0
        parts = [(g_prompt - g_cached, per_in), (g_cached, read_p), (g_out + thoughts, per_out)]
    else:
        return None
    if any(tokens < 0 or (tokens and price is None) for tokens, price in parts):
        return None
    cost = sum(tokens / 1_000_000 * (price or 0.0) for tokens, price in parts)
    if model.startswith(OFF_PEAK_HALF):
        from datetime import datetime, timezone
        if _off_peak(now or datetime.now(timezone.utc)):
            cost /= 2
    return cost


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
    Provider gate (review I1, refined by the M3 real-machine acceptance): the
    ollama protocol has NO per-token billing at all, so provider == "ollama" is
    $0 for ANY model tag — a prefix allowlist would leave e.g. "qwen2.5:0.5b"
    dishonestly unpriced (the acceptance run caught exactly that). Every other
    provider — including None — prices against the cloud table only, so a hosted
    "deepseek-r1" is honestly unpriced instead of labelled free.
    """
    if model is None or tokens_in is None or tokens_out is None:
        return None
    if provider == "ollama":
        return 0.0
    # Table is read at call time (not captured at import) so tests can patch it.
    table = PRICES
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
