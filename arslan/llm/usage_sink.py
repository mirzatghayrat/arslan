"""Per-turn token accounting via a contextvar — set around a user turn so the
LLMAdapter choke point can report tokens without threading state through callers."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_sink: ContextVar[list[int] | None] = ContextVar("usage_sink", default=None)
# S3-M3: per-(model, provider) buckets — {(model, provider): {"tokens_in", "tokens_out"}}.
# Replaces the old single last-model-wins dict: mixed-model turns (tool-loop model +
# synthesis adapter) misattributed the whole run to whichever model reported last.
_detail: ContextVar[dict[tuple[str | None, str | None], dict] | None] = ContextVar(
    "usage_detail", default=None
)


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
    """Structured usage from a provider response, accumulated into the call's
    (model, provider) bucket. A report with a None tokens_in/out (stream path, no
    usage frame) marks the bucket estimated via a STICKY flag — review I1: None-ness
    alone is erasable (a later real report into the same bucket would do
    (None or 0)+real and silently launder the estimated call's tokens into a
    real-flagged total). Real values still accumulate per-bucket regardless of the
    flag. No-op without context."""
    buckets = _detail.get()
    if buckets is None:
        return
    b = buckets.setdefault(
        (model, provider), {"tokens_in": None, "tokens_out": None, "estimated": False}
    )
    if tokens_in is None or tokens_out is None:
        # Sticky, never cleared: once ANY report into this bucket lacked real
        # numbers, the bucket's figures are incomplete for the whole collection.
        b["estimated"] = True
    if tokens_in is not None:
        b["tokens_in"] = (b["tokens_in"] or 0) + int(tokens_in)
    if tokens_out is not None:
        b["tokens_out"] = (b["tokens_out"] or 0) + int(tokens_out)


def primary() -> dict | None:
    """The bucket with the most total tokens (None fields count 0), as
    {model, provider, tokens_in, tokens_out} — or None when no context/reports.
    Ties break to the earliest-reported bucket (dict insertion order)."""
    buckets = _detail.get()
    if not buckets:
        return None
    (model, provider), b = max(
        buckets.items(),
        key=lambda kv: (kv[1]["tokens_in"] or 0) + (kv[1]["tokens_out"] or 0),
    )
    return {"model": model, "provider": provider,
            "tokens_in": b["tokens_in"], "tokens_out": b["tokens_out"]}


def detail() -> dict:
    """Snapshot of the structured usage. Backward-compatible top-level keys
    (model/provider = primary bucket — replaces last-model-wins; tokens_in/out =
    totals across buckets) plus a per-bucket breakdown under "buckets" (each row
    carries its sticky "estimated" flag).
    Honesty rule: ANY estimated bucket makes both totals None (estimates are never
    summed into real numbers) — generalizes the old any-None-field check, which a
    same-bucket real report could erase. All-None when no context/reports."""
    buckets = _detail.get()
    if not buckets:
        return {"tokens_in": None, "tokens_out": None,
                "model": None, "provider": None, "buckets": []}
    rows = [
        {"model": m, "provider": p,
         "tokens_in": b["tokens_in"], "tokens_out": b["tokens_out"],
         "estimated": b["estimated"]}
        for (m, p), b in buckets.items()
    ]
    # estimated goes True whenever a report leaves a field None, so the flag check
    # subsumes the old per-field None checks; keep them as defence in depth.
    blind = any(r["estimated"] for r in rows)
    tin = (None if blind or any(r["tokens_in"] is None for r in rows)
           else sum(r["tokens_in"] for r in rows))
    tout = (None if blind or any(r["tokens_out"] is None for r in rows)
            else sum(r["tokens_out"] for r in rows))
    prim = primary()
    return {"tokens_in": tin, "tokens_out": tout,
            "model": prim["model"], "provider": prim["provider"], "buckets": rows}


@contextmanager
def collecting():
    """Activate fresh accumulation buckets (total + structured) for the duration of the block."""
    bucket: list[int] = []
    detail_buckets: dict[tuple[str | None, str | None], dict] = {}
    token = _sink.set(bucket)
    dtoken = _detail.set(detail_buckets)
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
