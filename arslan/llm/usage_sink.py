"""Per-turn token accounting via a contextvar — set around a user turn so the
LLMAdapter choke point can report tokens without threading state through callers."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_sink: ContextVar[list[int] | None] = ContextVar("usage_sink", default=None)
_detail: ContextVar[dict | None] = ContextVar("usage_detail", default=None)


def report(tokens: int) -> None:
    """Add a token count to the active bucket (no-op when none is active)."""
    bucket = _sink.get()
    if bucket is not None:
        bucket.append(int(tokens))


def total() -> int:
    """Sum of the active bucket, or 0 when no context is active."""
    bucket = _sink.get()
    return sum(bucket) if bucket else 0


def report_detail(
    *,
    tokens_in: int | None,
    tokens_out: int | None,
    model: str | None,
    provider: str | None,
) -> None:
    """Structured usage from a real (non-stream) provider response. Aggregates in/out
    across the turn; keeps the latest non-null model/provider. No-op without context."""
    d = _detail.get()
    if d is None:
        return
    if tokens_in is not None:
        d["tokens_in"] = (d["tokens_in"] or 0) + int(tokens_in)
    if tokens_out is not None:
        d["tokens_out"] = (d["tokens_out"] or 0) + int(tokens_out)
    if model:
        d["model"] = model
    if provider:
        d["provider"] = provider


def detail() -> dict:
    """Snapshot of the structured usage, all-None when no context/reports."""
    d = _detail.get()
    return dict(d) if d else {"tokens_in": None, "tokens_out": None, "model": None, "provider": None}


@contextmanager
def collecting():
    """Activate fresh accumulation buckets (total + structured) for the duration of the block."""
    bucket: list[int] = []
    detail_bucket = {"tokens_in": None, "tokens_out": None, "model": None, "provider": None}
    token = _sink.set(bucket)
    dtoken = _detail.set(detail_bucket)
    try:
        yield bucket
    finally:
        _sink.reset(token)
        _detail.reset(dtoken)


def estimate_tokens(*parts: str | None) -> int:
    """Rough CJK-aware estimate: CJK chars ~1 token each, other chars ~4/token."""
    text = "".join(p for p in parts if p)
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return cjk + other // 4
