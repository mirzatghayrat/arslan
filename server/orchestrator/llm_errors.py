"""Turn a provider's billing / auth / rate refusal into something actionable.

WHY: OpenRouter answers a capped key with a wall of JSON — "requires more
credits, or fewer max_tokens… you requested up to 65536 tokens, but can only
afford 64381" — and we rendered it verbatim in the chat bubble, key-id URL and
all. Three different faults (empty account, capped key, oversized request) all
look identical in that blob, and none of the three remedies is obvious.

DELIBERATELY NARROW, for the same reason vision_errors is: mislabelling an
unrelated fault sends someone off topping up an account that was never the
problem. Anything unrecognised returns None and the raw error still shows.
"""
from __future__ import annotations

import re

# A key-level cap is NOT an empty account: the money may be there, sitting
# behind a per-key limit the user set and forgot. Different remedy, different
# sentence, and the metadata is what distinguishes them.
_KEY_LIMIT = re.compile(
    # OpenRouter says this two different ways with two different STATUS CODES:
    # 402 with `openrouter_key_limit` metadata, and 403 "Key limit exceeded
    # (total limit)". The sentence below existed for the 402 form only and was
    # therefore unreachable for the 403 one — a written answer that could never
    # be shown. Measured against a real key on 2026-08-24.
    r"openrouter_key_limit|api key's usage limit|key limit exceeded", re.I)
_PAYMENT = re.compile(r"402|payment required|insufficient (credits|balance|funds)", re.I)
# A model the account may not use FROM HERE. Not a key fault and not a money
# fault, and it is the one that looks most like both: same 403, same wall of
# JSON, and the remedy (change model, or change where the traffic leaves from)
# has nothing to do with either.
_REGION = re.compile(
    r"not available in your region|unsupported[_ ]country|region[_ ]not[_ ]supported"
    r"|country[,.]? region[,.]? or territory", re.I)
_AUTH = re.compile(r"401|unauthorized|invalid[_ ]api[_ ]key|authentication", re.I)
_RATE = re.compile(r"429|too many requests|rate.?limit", re.I)
_CONTEXT = re.compile(r"context[_ ]length|maximum context", re.I)
# Connection failures, including interruptions after sending. These errors do
# not establish whether the provider processed the request.
_TRANSPORT = re.compile(
    r"\bssl\b|certificate[_ ]verify|handshake|"
    r"connect(ion)?\s*(error|refused|reset|aborted|timed?\s*out)|"
    r"connecterror|connecttimeout|readtimeout|"
    r"eof occurred|remote end closed|econnreset|econnrefused|"
    r"network is unreachable|temporary failure in name resolution|"
    r"nodename nor servname|name or service not known|failed to establish",
    re.I)


def classify(raw_error: str) -> str | None:
    """Recognized category only; unknown diagnostics are not reinterpreted."""
    raw = raw_error or ""
    if not raw.strip():
        return None

    # Context length first: it co-occurs with token counts that read like money.
    if _CONTEXT.search(raw):
        return "context"

    # Transport first: a stray "401" inside a proxy's connection error should
    # not become an authentication verdict. Delivery status remains unknown.
    if _TRANSPORT.search(raw):
        return "transport"

    # A key cap answers with BOTH 402 and 403 depending on the provider, so this
    # is checked before either of them rather than nested inside one.
    if _KEY_LIMIT.search(raw):
        return "key_limit"

    if _REGION.search(raw):
        return "region"

    if _PAYMENT.search(raw):
        return "payment"

    if _AUTH.search(raw):
        return "auth"

    if _RATE.search(raw):
        return "rate"

    return None


def explain(raw_error: str, *, locale="zh") -> str | None:
    """Legacy synchronous default; production uses an explicit UI locale."""
    from server.services.provider_error_messages import render
    category = classify(raw_error)
    return render(category, locale) if category else None


async def explain_current(raw_error: str, *, had_images=False) -> str | None:
    from server.services.runtime_messages import selected_locale
    from server.orchestrator import vision_errors
    locale = await selected_locale()
    return vision_errors.explain(raw_error, had_images=had_images, locale=locale) or explain(raw_error, locale=locale)
