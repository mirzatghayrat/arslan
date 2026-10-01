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
