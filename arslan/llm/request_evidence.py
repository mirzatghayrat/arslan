"""Optional local request evidence, separate from admission and model adoption.

Providers pass their final JSON payload, never headers or credential-bearing URLs.
The trusted observer may return a callback for a successful HTTP response. It
only inspects the payload and grants no permission; evidence failure is non-fatal.
"""
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
import asyncio
import logging
from typing import Any

Acknowledgement = Callable[[], Awaitable[None]]
Observer = Callable[[dict[str, Any]], Awaitable[Acknowledgement | None]]
_observer: ContextVar[Observer | None] = ContextVar("model_request_evidence", default=None)
logger = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 0.5


@contextmanager
def bind(observer: Observer):
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


async def begin(payload: dict[str, Any]) -> Acknowledgement | None:
    observer = _observer.get()
    if observer is None:
        return None
    try:
        async with asyncio.timeout(_TIMEOUT_SECONDS):
            return await observer(payload)
    except Exception as exc:
        # Do not log an exception containing SQL, request content or secrets: its type only
        # (a CI run lost one record and the log could not say whether it was the timeout).
        logger.warning("Model request evidence could not be recorded (%s)", type(exc).__name__)
        return None


async def acknowledge(callback: Acknowledgement | None):
    if callback is not None:
        try:
            async with asyncio.timeout(_TIMEOUT_SECONDS):
                await callback()
        except Exception as exc:
            logger.warning("Model response evidence could not be recorded (%s)", type(exc).__name__)
