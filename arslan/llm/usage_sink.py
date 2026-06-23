"""Per-turn token accounting via a contextvar — set around a user turn so the
LLMAdapter choke point can report tokens without threading state through callers."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_sink: ContextVar[list[int] | None] = ContextVar("usage_sink", default=None)


def report(tokens: int) -> None:
    """Add a token count to the active bucket (no-op when none is active)."""
    bucket = _sink.get()
    if bucket is not None:
        bucket.append(int(tokens))


def total() -> int:
    """Sum of the active bucket, or 0 when no context is active."""
    bucket = _sink.get()
    return sum(bucket) if bucket else 0


@contextmanager
def collecting():
    """Activate a fresh accumulation bucket for the duration of the block."""
    bucket: list[int] = []
    token = _sink.set(bucket)
    try:
        yield bucket
    finally:
        _sink.reset(token)


def estimate_tokens(*parts: str | None) -> int:
    """Rough CJK-aware estimate: CJK chars ~1 token each, other chars ~4/token."""
    text = "".join(p for p in parts if p)
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return cjk + other // 4
