"""Optional request parameters a vendor stopped accepting, healed by resending.

Field report 2026-10-13: claude-sonnet-5-5 answered every request with 400
"`temperature` is deprecated for this model." — the key was fine, Arslan sent a
parameter the model had retired, and only a new release could fix it. Vendors
retire parameters on their own schedule (OpenAI's reasoning models refuse
`temperature` and want `max_completion_tokens` for `max_tokens`), so a table in
the code is only as new as the release it shipped in.

The rule here: a 400/422 that names, as refused, an optional parameter THIS
request sent is answered by resending without it — or under the name the error
asks for — and the endpoint+model is remembered once a resend succeeded.
Nothing else is retried: a parameter the request did not send is never
invented, a key/quota/rate error never matches, and each parameter is healed at
most once per request. Learning lives in this process only; after a restart the
first request costs one rejected (unbilled) round trip.
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

import httpx

T = TypeVar("T")

# Sampling knobs a request can do without. Never a parameter that changes what
# is asked (messages, tools, thinking switches): dropping those changes meaning.
_DROPPABLE = ("temperature", "top_p", "top_k")
# OpenAI's reasoning models: "Use 'max_completion_tokens' instead." Renamed only
# when the error itself names the new key, so the budget is kept, never lost.
_RENAMES = {"max_tokens": "max_completion_tokens"}
# Containers a parameter may sit in (Gemini: generationConfig.temperature).
_NESTED = ("generationConfig",)

_REFUSED = re.compile(
    r"unsupported|not supported|deprecated|does not support|no longer (?:accepted|supported)|"
    r"not allowed|not permitted|only the default|unknown (?:parameter|field|argument)|"
    r"unrecognized|extra (?:inputs|fields) are not permitted", re.I)

_learned: dict[str, dict[str, str | None]] = {}


def forget() -> None:
    """Tests only: drop everything learned in this process."""
    _learned.clear()


def _containers(payload: dict[str, Any]):
    yield payload
    for name in _NESTED:
        inner = payload.get(name)
        if isinstance(inner, dict):
            yield inner


def _change(payload: dict[str, Any], key: str, new: str | None) -> bool:
    for box in _containers(payload):
        if key in box:
            value = box.pop(key)
            if new is not None:
                box[new] = value
            return True
    return False


def prepare(fingerprint: str, payload: dict[str, Any]) -> None:
    """Apply what this endpoint+model already refused, before the first send."""
    for key, new in _learned.get(fingerprint, {}).items():
        _change(payload, key, new)


def _error_text(response: httpx.Response) -> str:
    """The raw body: a vendor's message and its `param` field both live there."""
    try:
        return response.text or ""
    except Exception:  # noqa: BLE001 — a body that cannot be read heals nothing
        return ""


def _named(key: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text) is not None


def recover(exc: httpx.HTTPStatusError, payload: dict[str, Any],
            healed: list[tuple[str, str | None]]) -> bool:
    """True when `payload` was changed and should be sent again."""
    if exc.response.status_code not in (400, 422):
        return False
    text = _error_text(exc.response)
    if not _REFUSED.search(text):
        return False
    # A key healed once is gone from the payload, so nothing is healed twice and
    # the resends are bounded by the parameters the request carried.
    for key in (*_DROPPABLE, *_RENAMES):
        if not _named(key, text):
            continue
        new = _RENAMES.get(key)
        if new is not None and not _named(new, text):
            continue
        if _change(payload, key, new):
            healed.append((key, new))
            return True
    return False


def settle(fingerprint: str, healed: list[tuple[str, str | None]]) -> None:
    """Remember what the successful resend did without."""
    if healed:
        _learned.setdefault(fingerprint, {}).update(healed)


async def send(fingerprint: str, payload: dict[str, Any],
               attempt: Callable[[dict[str, Any]], Awaitable[T]]) -> T:
    """One request: `attempt(payload)` is a single HTTP send that raises
    httpx.HTTPStatusError (body readable) on an error status."""
    prepare(fingerprint, payload)
    healed: list[tuple[str, str | None]] = []
    while True:
        try:
            result = await attempt(payload)
        except httpx.HTTPStatusError as exc:
            if recover(exc, payload, healed):
                continue
            raise
        settle(fingerprint, healed)
        return result


async def stream(fingerprint: str, payload: dict[str, Any],
                 attempt: Callable[[dict[str, Any]], AsyncIterator[T]]) -> AsyncIterator[T]:
    """As send(), for a streamed reply: resent only if it failed before its first item."""
    prepare(fingerprint, payload)
    healed: list[tuple[str, str | None]] = []
    while True:
        started = False
        try:
            async for item in attempt(payload):
                started = True
                yield item
        except httpx.HTTPStatusError as exc:
            if not started and recover(exc, payload, healed):
                continue
            raise
        settle(fingerprint, healed)
        return
