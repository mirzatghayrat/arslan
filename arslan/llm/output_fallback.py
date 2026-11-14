"""v0.1.64: one resend at 8,192 when an endpoint refuses the declared output cap.

OpenAI-compatible and Gemini keys now declare the model's documented maximum, or 32,768 for an
unknown model (output_budget.for_model). A custom or smaller model may allow less, and OpenRouter
refuses a cap the key's credit cannot cover (402 "... or fewer max_tokens"). Such a refusal (400, 402
or 422 whose message names the cap parameter this request sent) is answered by sending the same
request again, once, at output_budget.REFUSED_CAP_FALLBACK. Anything else is raised as before. A
refused request was not generated, so it is not billed. Wraps param_heal, which still renames or
drops what an endpoint refuses first.
"""
from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

import httpx

from arslan.llm import param_heal
from arslan.llm.output_budget import REFUSED_CAP_FALLBACK

T = TypeVar("T")
logger = logging.getLogger(__name__)

_STATUSES = (400, 402, 422)
_TOP_LEVEL = ("max_completion_tokens", "max_tokens")      # OpenAI-compatible bodies
_GEMINI = ("generationConfig", "maxOutputTokens")
# A refusal of the parameter itself, not of its size: param_heal's to rename or drop, never resent here.
_PARAMETER_REFUSED = re.compile(r"unsupported parameter|not supported|unknown (?:parameter|field|name)|"
                                r"unrecognized|extra (?:inputs|fields)|cannot find field|deprecated", re.I)


def _squashed(text: str) -> str:
    """Lower case without separators: "maxOutputTokens", "max_output_tokens" and "max output tokens" agree."""
    return re.sub(r"[\s_\-`'\"]", "", text.lower())


def _slot(payload: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    for key in _TOP_LEVEL:
        if key in payload:
            return payload, key
    config = payload.get(_GEMINI[0])
    if isinstance(config, dict) and _GEMINI[1] in config:
        return config, _GEMINI[1]
    return None


def lowered(exc: httpx.HTTPStatusError, payload: dict[str, Any]) -> bool:
    """Set the cap to the fallback when `exc` refused it; True when `payload` changed."""
    if exc.response.status_code not in _STATUSES:
        return False
    slot = _slot(payload)
    if slot is None:
        return False
    box, key = slot
    if not isinstance(box[key], int) or box[key] <= REFUSED_CAP_FALLBACK:
        return False
    try:
        text = exc.response.text or ""
    except Exception:  # noqa: BLE001 — a body that cannot be read names nothing
        return False
    if _squashed(key) not in _squashed(text) or _PARAMETER_REFUSED.search(text):
        return False
    logger.info("Model endpoint refused %s=%d; sending once more at %d", key, box[key], REFUSED_CAP_FALLBACK)
    box[key] = REFUSED_CAP_FALLBACK
    return True


async def send(fingerprint: str, payload: dict[str, Any],
               attempt: Callable[[dict[str, Any]], Awaitable[T]]) -> T:
    """param_heal.send, sent once more at the fallback cap when the cap was refused."""
    try:
        return await param_heal.send(fingerprint, payload, attempt)
    except httpx.HTTPStatusError as exc:
        if not lowered(exc, payload):
            raise
    return await param_heal.send(fingerprint, payload, attempt)


async def stream(fingerprint: str, payload: dict[str, Any],
                 attempt: Callable[[dict[str, Any]], AsyncIterator[T]]) -> AsyncIterator[T]:
    """param_heal.stream, likewise; only a refusal before the first item is sent again."""
    started = False
    try:
        async for item in param_heal.stream(fingerprint, payload, attempt):
            started = True
            yield item
        return
    except httpx.HTTPStatusError as exc:
        if started or not lowered(exc, payload):
            raise
    async for item in param_heal.stream(fingerprint, payload, attempt):
        yield item
