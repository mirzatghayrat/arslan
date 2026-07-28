"""Provider HTTP errors that actually say what went wrong.

httpx's `raise_for_status()` produces only a status line:

    Client error '400 Bad Request' for url 'https://api.deepseek.com/…'

The reason is in the response BODY, which that message discards. Shipping that
to a user is useless on its own, and it also broke the vision-error copy
(server/orchestrator/vision_errors.py) in the field: it matches the provider's
own wording, and the wording never reached it. Found on a real machine in
v0.1.9 — the unit tests had passed because they were written against invented
error strings rather than any this code produces.
"""
from __future__ import annotations

import httpx

# Long enough for a provider's message, short enough that an HTML error page or
# a giant JSON dump does not become the whole screen.
_MAX_BODY = 900


def with_body(exc: httpx.HTTPStatusError) -> str:
    """The status line plus whatever the provider said about it."""
    base = str(exc)
    try:
        body = (exc.response.text or "").strip()
    except Exception:  # noqa: BLE001 — never let error formatting raise
        return base
    if not body:
        return base
    if len(body) > _MAX_BODY:
        body = body[:_MAX_BODY] + "…"
    return f"{base}\n{body}"
