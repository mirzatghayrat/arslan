"""S3-M3 cost visibility: usage_ledger — best-effort per-scope token accounting.

Live dispatch Runs already persist their usage on the Run row (RunRecorder.finalize).
Every OTHER LLM call site — router decision, judge scoring, memory compaction, titler,
Arslan's answer path, direct spawn chat — previously burned tokens invisibly. `scope()`
wraps such a call site: it opens a fresh ``usage_sink.collecting()`` bucket and, on
exit, writes one ledger row per (model, provider) bucket.

Nesting safety: ``usage_sink.collecting()`` is set-on-enter / reset-on-exit contextvars,
so a scope opened inside an ALREADY-collecting region (or in a task that inherited an
active bucket via ``asyncio.create_task`` — e.g. the judge task scheduled from inside
_dispatch_spawn's collecting block) sees ONLY its own usage, and the outer bucket
resumes untouched on exit. Nothing is stolen, nothing double-counted
(proved by tests/server/test_usage_ledger.py::test_judge_scope_does_not_diminish_...).

Honesty rules (mirror usage_sink.detail() / RunRecorder.finalize):
  - a bucket with real tokens_in/out → real row, tokens_estimated=False;
  - a bucket the adapter could only estimate (both fields None — the estimate was
    reported via report() only) → when it is the single blind bucket, it honestly
    owns the unattributed remainder of usage_sink.total(); tokens_estimated=True;
  - report() fired with no detail at all (pure-estimate, no model attribution) →
    one scope-only row with the estimated total.
Best-effort: the DB write is wrapped — a ledger failure must NEVER break the call.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from arslan.llm import usage_sink
from server.db import session as db_session
from server.db.models import UsageLedger

logger = logging.getLogger(__name__)


def _build_rows(scope_name: str, conversation_id: str | None,
                run_id: int | None) -> list[UsageLedger]:
    detail = usage_sink.detail()
    buckets = detail["buckets"]
    sink_total = usage_sink.total()
    ts = datetime.utcnow()
    common = {"ts": ts, "scope": scope_name,
              "conversation_id": conversation_id, "run_id": run_id}
    if not buckets:
        if sink_total <= 0:
            return []
        return [UsageLedger(**common, model=None, provider=None,
                            tokens_in=None, tokens_out=None,
                            tokens_total=sink_total, tokens_estimated=True)]

    real_sum = sum((b["tokens_in"] or 0) + (b["tokens_out"] or 0) for b in buckets)
    blind = [b for b in buckets if b["tokens_in"] is None and b["tokens_out"] is None]
    # The adapter's estimate fallback reports the estimated total ONLY via report()
    # (detail gets a both-None bucket): with exactly one blind bucket the remainder
    # is honestly its estimate; with several, attribution would be guesswork → 0.
    # Review S1 — known frame-vs-ledger discrepancy in the est-then-real SAME-bucket
    # case: the real report fills the bucket's fields, so it no longer counts as
    # blind here and the estimate's remainder is dropped — the ledger row keeps only
    # the attributable real portion (sticky-estimated flag preserved), while the
    # turn's stream_end frame total still includes the estimate via
    # usage_sink.total(). Deliberate: per-row attribution beats matching a blurred
    # total (tested at 500-estimate→140-real in
    # test_scope_same_bucket_estimate_then_real_row_marked_estimated).
    unattributed = max(sink_total - real_sum, 0)
    rows: list[UsageLedger] = []
    for b in buckets:
        tin, tout = b["tokens_in"], b["tokens_out"]
        total = (tin or 0) + (tout or 0)
        if tin is None and tout is None and len(blind) == 1:
            total = unattributed
        # Review I1 alignment: the bucket's STICKY estimated flag is the truth —
        # a same-bucket estimate-then-real sequence leaves real-looking fields but
        # stays estimated. Fall back to the old None check if the flag is absent.
        rows.append(UsageLedger(**common, model=b["model"], provider=b["provider"],
                                tokens_in=tin, tokens_out=tout, tokens_total=total,
                                tokens_estimated=bool(b.get("estimated", tin is None))))
    return rows


async def _write(scope_name: str, conversation_id: str | None, run_id: int | None) -> None:
    rows = _build_rows(scope_name, conversation_id, run_id)
    if not rows:
        return
    async with db_session.AsyncSessionLocal() as db:
        for r in rows:
            db.add(r)
        await db.commit()


@asynccontextmanager
async def scope(scope_name: str, conversation_id: str | None = None, *,
                run_id: int | None = None):
    """Collect LLM usage for the wrapped block and ledger it under ``scope_name``.

    The ledger row is written on EVERY exit (tokens burned on a failing call are
    still tokens burned), but the write itself is best-effort — an accounting
    failure is logged and swallowed, never surfaced to the business call.
    """
    with usage_sink.collecting():
        try:
            yield
        finally:
            try:
                await _write(scope_name, conversation_id, run_id)
            except Exception as exc:  # noqa: BLE001 — accounting is never fatal
                logger.warning("usage_ledger write failed (non-fatal, scope=%s): %s",
                               scope_name, exc)
