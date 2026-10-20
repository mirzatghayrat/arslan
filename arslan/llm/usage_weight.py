"""Budget weight of one model response (0.1.49 P1.2, design section 5.3).

The execution budget is a runaway guard, so it should track what a request
costs, not raw token counts: a cached prefix re-read every step (which the
native protocol makes the common case) costs ~1/30 of an uncached token at
DeepSeek prices. Weight = uncached input + 0.1 x cached input + output.
Returns None when the usage carries no cache breakdown (caller charges the
raw total, exactly as before).
"""
from __future__ import annotations

from typing import Any

CACHED_WEIGHT = 0.1


def _int(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def charged_tokens(usage: dict[str, Any] | None) -> int | None:
    u = usage or {}
    # DeepSeek: explicit hit/miss split.
    hit, miss = _int(u.get("prompt_cache_hit_tokens")), _int(u.get("prompt_cache_miss_tokens"))
    out = _int(u.get("completion_tokens"))
    if hit is not None and miss is not None and out is not None:
        return round(miss + CACHED_WEIGHT * hit + out)
    # OpenAI: prompt_tokens includes cached_tokens.
    details = u.get("prompt_tokens_details") if isinstance(u.get("prompt_tokens_details"), dict) else {}
    cached, prompt = _int(details.get("cached_tokens")), _int(u.get("prompt_tokens"))
    if cached is not None and prompt is not None and out is not None and cached <= prompt:
        return round(prompt - cached + CACHED_WEIGHT * cached + out)
    # Anthropic: input_tokens excludes cache reads and cache writes.
    read = _int(u.get("cache_read_input_tokens"))
    a_in, a_out = _int(u.get("input_tokens")), _int(u.get("output_tokens"))
    if read is not None and a_in is not None and a_out is not None:
        written = _int(u.get("cache_creation_input_tokens")) or 0
        return round(a_in + written + CACHED_WEIGHT * read + a_out)
    # Gemini: promptTokenCount includes cachedContentTokenCount.
    g_cached, g_prompt = _int(u.get("cachedContentTokenCount")), _int(u.get("promptTokenCount"))
    g_out = _int(u.get("candidatesTokenCount"))
    if g_cached is not None and g_prompt is not None and g_out is not None and g_cached <= g_prompt:
        thoughts = _int(u.get("thoughtsTokenCount")) or 0
        return round(g_prompt - g_cached + CACHED_WEIGHT * g_cached + g_out + thoughts)
    return None


def cache_split(usage: dict[str, Any] | None) -> dict[str, int | None] | None:
    """0.1.63 K3: {cache_read, cache_write, input_total} of one response, or None when it reports no
    cache. input_total is the whole input: Anthropic's input_tokens leaves out cache reads and writes,
    the others already count them. cache_write is None where the provider does not report writes."""
    u = usage or {}
    read, a_in = _int(u.get("cache_read_input_tokens")), _int(u.get("input_tokens"))
    if a_in is not None and "prompt_tokens" not in u:                   # Anthropic (cache fields optional)
        read, written = read or 0, _int(u.get("cache_creation_input_tokens")) or 0
        return {"cache_read": read, "cache_write": written, "input_total": a_in + read + written}
    prompt = _int(u.get("prompt_tokens"))
    hit = _int(u.get("prompt_cache_hit_tokens"))                         # DeepSeek
    details = u.get("prompt_tokens_details") if isinstance(u.get("prompt_tokens_details"), dict) else {}
    cached = hit if hit is not None else _int(details.get("cached_tokens"))  # OpenAI
    if prompt is not None and cached is not None and cached <= prompt:
        return {"cache_read": cached, "cache_write": None, "input_total": prompt}
    g_cached, g_prompt = _int(u.get("cachedContentTokenCount")), _int(u.get("promptTokenCount"))
    if g_cached is not None and g_prompt is not None and g_cached <= g_prompt:   # Gemini
        return {"cache_read": g_cached, "cache_write": None, "input_total": g_prompt}
    return None
