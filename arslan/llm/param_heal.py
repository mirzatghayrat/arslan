"""Optional request parameters a vendor stopped accepting, healed by resending.

Field report 2026-10-13: claude-sonnet-5-5 answered every request with 400
"`temperature` is deprecated for this model." — the key was fine, Arslan sent a
parameter the model had retired, and only a new release could fix it. Vendors
retire parameters on their own schedule (OpenAI's reasoning models refuse
`temperature` and want `max_completion_tokens` for `max_tokens`), so a table in
the code is only as new as the release it shipped in.

The rule here: a 400/422 that names, as refused, an optional parameter THIS
request sent is answered by resending without it — or under the name the error
asks for. Nothing else is retried: a parameter the request did not send is
never invented, a key/quota/rate error never matches, and a parameter healed
once is gone from the payload, so the resends are bounded by what it carried.

What is remembered (per endpoint+model, in this process only) is narrower than
what is tried: a heal counts only when the answer after it stopped naming its
parameter — a success, or an error about something else. A strict server that
lists the fields it DOES accept names `temperature` again, and that drop is
never learned. After a restart the first request re-learns with one rejected
(unbilled) round trip.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

import httpx

T = TypeVar("T")
logger = logging.getLogger(__name__)

# Sampling knobs a request can do without. Never a parameter that changes what
# is asked (messages, tools, thinking switches): dropping those changes meaning.
_DROPPABLE = ("temperature", "top_p", "top_k", "block_binding", "context_management", "ttl")
# 0.1.63 K3: `ttl` sits inside every cache_control marker (system, tool and message blocks). Refused, it
# goes from every marker; the markers stay (the default five-minute cache).
_IN_MARKERS = ("ttl",)
# 0.1.63 K1: an opt-in beta field and the `anthropic-beta` value that enables it go together. An
# endpoint that refuses either (a proxy, an older API version) gets both dropped and remembered;
# the request means the same without them (the caller trims context itself instead, K1b). Betas
# travel in the payload's private "_betas" list until the provider turns it into the header.
_BETA_OF = {"block_binding": "thinking-binding-controls-2026-08-01",
            "context_management": "context-management-2025-06-27"}
# OpenAI's reasoning models: "Use 'max_completion_tokens' instead." Renamed only
# when the error itself names the new key, so the budget is kept, never lost.
_RENAMES = {"max_tokens": "max_completion_tokens"}
# Containers a parameter may sit in (Gemini: generationConfig.temperature).
_NESTED = ("generationConfig", "thinking")

_REFUSED = re.compile(
    r"unsupported|not supported|deprecated|does not support|no longer (?:accepted|supported)|"
    r"not allowed|not permitted|only the default|unknown (?:parameter|field|argument|name)|"
    r"unrecognized|extra (?:inputs|fields) are not permitted|cannot find field|unexpected value", re.I)

_learned: dict[str, dict[str, str | None]] = {}


def forget() -> None:
    """Tests only: drop everything learned in this process."""
    _learned.clear()


def refused(fingerprint: str, key: str) -> bool:
    """Whether this endpoint+model is known to refuse `key` (it is left out of every request)."""
    learned = _learned.get(fingerprint, {})
    return key in learned and learned[key] is None


def _containers(payload: dict[str, Any]):
    yield payload
    for name in _NESTED:
        inner = payload.get(name)
        if isinstance(inner, dict):
            yield inner


def _markers(payload: dict[str, Any]):
    """Every cache_control object of an Anthropic payload."""
    blocks = [*(payload.get("system") if isinstance(payload.get("system"), list) else []),
              *(payload.get("tools") if isinstance(payload.get("tools"), list) else [])]
    for message in payload.get("messages") if isinstance(payload.get("messages"), list) else []:
        content = message.get("content") if isinstance(message, dict) else None
        blocks += content if isinstance(content, list) else []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("cache_control"), dict):
            yield block["cache_control"]


def _sent(payload: dict[str, Any]) -> set[str]:
    keys = {key for box in _containers(payload) for key in box}
    return keys | {key for marker in _markers(payload) for key in marker if key in _IN_MARKERS}


def _change(payload: dict[str, Any], key: str, new: str | None) -> bool:
    if key in _IN_MARKERS:
        found = [marker for marker in _markers(payload) if key in marker]
        for marker in found:
            del marker[key]
        return bool(found)
    for box in _containers(payload):
        if key in box:
            value = box.pop(key)
            if new is not None:
                box[new] = value
            beta = _BETA_OF.get(key)
            betas = payload.get("_betas")
            if beta and isinstance(betas, list) and beta in betas:
                betas.remove(beta)
            return True
    return False


def prepare(fingerprint: str, payload: dict[str, Any]) -> None:
    """Apply what this endpoint+model already refused, before the first send."""
    for key, new in _learned.get(fingerprint, {}).items():
        _change(payload, key, new)


def _reason(response: httpx.Response) -> tuple[str, str | None]:
    """The vendor's message (error.message when the body is the usual JSON, else
    the raw body) and the parameter it blames (OpenAI's error.param), if any."""
    try:
        text = response.text or ""
    except Exception:  # noqa: BLE001 — a body that cannot be read heals nothing
        return "", None
    try:
        data = json.loads(text)
    except ValueError:
        return text, None
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, dict):
        return text, None
    message, param = err.get("message"), err.get("param")
    return (message if isinstance(message, str) and message else text,
            param if isinstance(param, str) else None)


def _position(key: str, text: str) -> int | None:
    found = re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text)
    return found.start() if found else None


class Heals:
    """The resends of one request, and which of them earned remembering."""

    def __init__(self) -> None:
        self.pending: tuple[str, str | None] | None = None
        self.kept: list[tuple[str, str | None]] = []

    def judge(self, message: str | None) -> None:
        """The answer after the last heal: None = success, else its message."""
        if self.pending is not None:
            if message is None or _position(self.pending[0], message) is None:
                self.kept.append(self.pending)
            self.pending = None


def recover(exc: httpx.HTTPStatusError, payload: dict[str, Any], heals: Heals) -> bool:
    """True when `payload` was changed and should be sent again."""
    if exc.response.status_code not in (400, 422):
        heals.judge("")
        return False
    message, param = _reason(exc.response)
    heals.judge(message)
    if not _REFUSED.search(message):
        return False
    sent = _sent(payload)
    candidates: dict[str, int] = {}
    for key in (*_DROPPABLE, *_RENAMES):
        at = _position(key, message)
        if at is None and key in _BETA_OF:
            at = _position(_BETA_OF[key], message)       # the beta value named instead of the field
        if key not in sent or (at is None and key != param):
            continue
        new = _RENAMES.get(key)
        if new is not None and _position(new, message) is None:
            continue
        candidates[key] = at or 0
    if param is not None:
        # The vendor said which parameter; anything else it names is context.
        candidates = {param: 0} if param in candidates else {}
    if not candidates:
        return False
    # Otherwise the one named first: "unknown field `max_tokens`, expected one of
    # …, `temperature`" blames max_tokens, not the field it says it accepts.
    key = min(candidates, key=candidates.__getitem__)
    new = _RENAMES.get(key)
    if not _change(payload, key, new):
        return False        # nothing changed: resending would loop
    heals.pending = (key, new)
    logger.info("Model endpoint refused %r; sending again %s", key,
                f"as {new!r}" if new else "without it")
    return True


def settle(fingerprint: str, heals: Heals) -> None:
    """The request succeeded: remember the heals that earned it."""
    heals.judge(None)
    if heals.kept:
        _learned.setdefault(fingerprint, {}).update(heals.kept)
        logger.info("Remembered for this model endpoint: %s", ", ".join(
            f"{key} -> {new}" if new else f"no {key}" for key, new in heals.kept))
        heals.kept = []


async def send(fingerprint: str, payload: dict[str, Any],
               attempt: Callable[[dict[str, Any]], Awaitable[T]]) -> T:
    """One request: `attempt(payload)` is a single HTTP send that raises
    httpx.HTTPStatusError (body readable) on an error status."""
    prepare(fingerprint, payload)
    heals = Heals()
    while True:
        try:
            result = await attempt(payload)
        except httpx.HTTPStatusError as exc:
            if recover(exc, payload, heals):
                continue
            raise
        settle(fingerprint, heals)
        return result


async def stream(fingerprint: str, payload: dict[str, Any],
                 attempt: Callable[[dict[str, Any]], AsyncIterator[T]]) -> AsyncIterator[T]:
    """As send(), for a streamed reply: resent only if it failed before its
    first item, and settled at that first item (a reader may stop early)."""
    prepare(fingerprint, payload)
    heals = Heals()
    while True:
        started = False
        try:
            async for item in attempt(payload):
                if not started:
                    started = True
                    settle(fingerprint, heals)
                yield item
        except httpx.HTTPStatusError as exc:
            if not started and recover(exc, payload, heals):
                continue
            raise
        if not started:
            settle(fingerprint, heals)
        return
