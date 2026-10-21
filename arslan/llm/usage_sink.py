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


# 0.1.58 §6: the latest call's input — how full the context is now (the composer's ring).
_last_in: ContextVar[dict | None] = ContextVar("usage_last_in", default=None)


def last_input() -> int | None:
    holder = _last_in.get()
    return holder["value"] if holder else None


# 0.1.63 K4b: what the latest request was made of (system, tools, context, history, turn), estimated
# with context_budget.estimate_tokens — the ring's breakdown. Its total stays last_input (the bill's).
_parts: ContextVar[dict | None] = ContextVar("usage_context_parts", default=None)


def note_context_parts(parts: dict[str, int] | None) -> None:
    holder = _parts.get()
    if holder is not None:
        holder["value"] = dict(parts) if parts is not None else None


def context_parts() -> dict[str, int] | None:
    holder = _parts.get()
    return holder["value"] if holder else None


_NO_PRICE_INFO = object()


def report(tokens: int, *, charged: int | None = None, usd=_NO_PRICE_INFO) -> None:
    """Add a token count to the active bucket (no-op when none is active).

    `charged` is what the execution budget is debited (0.1.49 S5: cached input
    weighted, arslan/llm/usage_weight.py); the bucket keeps the raw count.
    K4a: `usd` is the response's price (prices.usd_for_usage; None = not known), charged to the run's dollar
    cap; a caller that says nothing about price charges nothing there."""
    bucket = _sink.get()
    from arslan.execution_budget import charge_tokens, charge_usd
    charge_tokens(tokens if charged is None else charged)
    if usd is not _NO_PRICE_INFO:
        charge_usd(usd)
    if bucket is not None:
        bucket.append(int(tokens))


def calls() -> int:
    """How many model calls reported into the active bucket (0.1.58: the reply's usage
    popover says "调用模型 N 次" — why a short answer can carry a large input total)."""
    bucket = _sink.get()
    return len(bucket) if bucket else 0


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
    cache_read: int | None = None,
    cache_write: int | None = None,
    input_total: int | None = None,
    usd: float | None = None,
) -> None:
    """Structured usage from a provider response, accumulated into the call's
    (model, provider) bucket. A report with a None tokens_in/out (stream path, no
    usage frame) marks the bucket estimated via a STICKY flag — review I1: None-ness
    alone is erasable (a later real report into the same bucket would do
    (None or 0)+real and silently launder the estimated call's tokens into a
    real-flagged total). Real values still accumulate per-bucket regardless of the
    flag. No-op without context.

    0.1.63 K3: `input_total` is the whole input when it differs from tokens_in (Anthropic's input_tokens
    leaves out cache reads and writes); the ring reads it. `cache_read` / `cache_write` add up per bucket
    when the provider reports them.

    K4a: `usd` is the response's price by cache tier (prices.usd_for_usage); it adds up per bucket, and a
    real report without one marks the bucket's dollars incomplete (sticky `usd_missing`)."""
    whole = input_total if input_total is not None else tokens_in
    holder = _last_in.get()
    if holder is not None and whole is not None:
        holder["value"] = int(whole)
    buckets = _detail.get()
    if buckets is None:
        return
    b = buckets.setdefault(
        (model, provider), {"tokens_in": None, "tokens_out": None, "estimated": False,
                            "cache_read": None, "cache_write": None, "input_total": None,
                            "usd": None, "usd_missing": False}
    )
    if usd is None:
        b["usd_missing"] = True
    else:
        b["usd"] = (b["usd"] or 0.0) + float(usd)
    for key, value in (("cache_read", cache_read), ("cache_write", cache_write), ("input_total", whole)):
        if value is not None:
            b[key] = (b[key] or 0) + int(value)
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
        return {"tokens_in": None, "tokens_out": None, "cache_read": None, "input_total": None,
                "model": None, "provider": None, "buckets": []}
    rows = [
        {"model": m, "provider": p,
         "tokens_in": b["tokens_in"], "tokens_out": b["tokens_out"],
         "estimated": b["estimated"], "usd": None if b["usd_missing"] else b["usd"]}
        for (m, p), b in buckets.items()
    ]
    # estimated goes True whenever a report leaves a field None, so the flag check
    # subsumes the old per-field None checks; keep them as defence in depth.
    blind = any(r["estimated"] for r in rows)
    tin = (None if blind or any(r["tokens_in"] is None for r in rows)
           else sum(r["tokens_in"] for r in rows))
    tout = (None if blind or any(r["tokens_out"] is None for r in rows)
            else sum(r["tokens_out"] for r in rows))
    # K3: the whole input and the cache reads, under the same honesty rule; cache_read is None unless
    # some bucket reported one (a provider that says nothing about its cache gets no hit rate).
    whole = [b["input_total"] for b in buckets.values()]
    reads = [b["cache_read"] for b in buckets.values() if b["cache_read"] is not None]
    input_total = None if blind or any(v is None for v in whole) else sum(whole)
    cache_read = None if blind or not reads else sum(reads)
    prim = primary()
    return {"tokens_in": tin, "tokens_out": tout, "cache_read": cache_read, "input_total": input_total,
            "model": prim["model"], "provider": prim["provider"], "buckets": rows}


@contextmanager
def collecting():
    """Activate fresh accumulation buckets (total + structured) for the duration of the block."""
    bucket: list[int] = []
    detail_buckets: dict[tuple[str | None, str | None], dict] = {}
    token = _sink.set(bucket)
    dtoken = _detail.set(detail_buckets)
    ltoken = _last_in.set({"value": None})
    ptoken = _parts.set({"value": None})
    try:
        yield bucket
    finally:
        _sink.reset(token)
        _detail.reset(dtoken)
        _last_in.reset(ltoken)
        _parts.reset(ptoken)
