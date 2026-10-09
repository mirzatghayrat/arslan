"""S3-M3 cost visibility: fleet-wide usage summary (visibility only — no budgets).

Two sources, one view: spawn runs keep their usage on the Run row (kind='live' as
scope "spawn" and kind='scheduled' as scope "scheduled" — Task-2 review I2, 成本只可见:
scheduled fires burn real tokens in real conversations, they count everywhere;
kind='replay' only behind include_replay), every other LLM call site writes
usage_ledger rows. Both are fetched raw and aggregated in Python — pricing needs a
per-item longest-prefix model lookup (arslan/llm/prices.py) plus the estimated-flag
honesty gate, which SQL grouping would only obscure at this data volume.

Honesty rules (shared with /conversations/{id}/usage via item_usd):
  - an item is priced ONLY when its tokens are real (not estimated) AND the model has
    a known price — otherwise it contributes tokens but usd stays None;
  - a group/total with zero priceable items reports usd=None (unknown ≠ free);
  - NOT_COVERED lists the call sites that don't feed the ledger yet (spec §S3-D
    未计入清单) — the summary page renders it as a footnote instead of pretending
    full coverage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from arslan.llm import prices
from server.auth import require_auth
from server.db import session as db_session
from server.db.models import Run, UsageLedger
from server.schemas import (
    UsageBinOut,
    UsageDailyPointOut,
    UsageRunsOut,
    UsageSummaryOut,
    UsageSummaryRowOut,
)

router = APIRouter(dependencies=[Depends(require_auth)])

# LLM call sites NOT ledgered yet — mirrors spec §S3-D's 未计入清单 annotation
# (2026-07-11-s3-table-stakes-design.md). Update BOTH places when wiring a new scope.
NOT_COVERED = [
    "_route_announcement",
    "compare_judge",
    "optimizer",
    "synthetic_corpus",
    "spawn_drafter",
    "spawn_match_service",
    "staffing_gather",
    "update_drafter",
    "equipment_service",
    "fact_classify",
    "ingest",
    "storage_intent",
    "tool_intent",
    "mcp_suggest",
    "skill_suggest",
    "learning_service",
    "note_service",
    "sandbox_service",
]

_WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
# Activity dashboard slices: 24 hours, 28 quarter-days, 30 days.
_BIN = {"24h": timedelta(hours=1), "7d": timedelta(hours=6), "30d": timedelta(days=1)}
# Upper bounds (ms) of the duration bands; the last band is open-ended.
DURATION_BANDS = ((10_000, "<10s"), (30_000, "10–30s"), (60_000, "30s–1m"), (180_000, "1–3m"),
                  (600_000, "3–10m"), (None, ">10m"))
_RUN_KINDS = ("live", "host", "scheduled")
_DONE = {"completed", "recorded", "scored"}
_STOPPED = {"cancelled", "interrupted"}


def _band(ms: int) -> int:
    return next(i for i, (upper, _) in enumerate(DURATION_BANDS) if upper is None or ms < upper)


def _percentile(sorted_ms: list[int], q: float) -> int | None:
    """Nearest-rank percentile: the smallest value with at least q of the data at or below it."""
    if not sorted_ms:
        return None
    rank = max(1, -(-len(sorted_ms) * q // 1))      # ceil(n*q)
    return sorted_ms[int(rank) - 1]


def run_activity(runs: list[tuple], items: list[tuple], since: datetime, now: datetime,
                 rng: str) -> tuple[UsageRunsOut, list[UsageBinOut]]:
    """Totals and per-slice series from (status, total_ms, created_at) run rows and
    usage items (…, tokens_total, ts). Pure, so the shapes are tested without a DB."""
    step = _BIN[rng]
    count = max(1, int((now - since) / step))
    start = now - step * count
    # Stored times are naive UTC; the epoch makes the browser's local-time labels exact.
    bins = [UsageBinOut(start_ts=int((start + step * i).replace(tzinfo=timezone.utc).timestamp()),
                        durations=[0] * len(DURATION_BANDS)) for i in range(count)]

    def slot(ts: datetime | None) -> int | None:
        if ts is None or ts < start:
            return None
        return min(count - 1, int((ts - start) / step))

    totals = UsageRunsOut()
    finished: list[int] = []
    per_bin_ms: dict[int, list[int]] = {}
    for status, total_ms, created in runs:
        totals.total += 1
        kind = ("running" if status == "recording" else "failed" if status == "failed"
                else "stopped" if status in _STOPPED else "done")
        setattr(totals, kind, getattr(totals, kind) + 1)
        index = slot(created)
        if index is not None:
            bins[index].runs += 1
            bins[index].failed += kind == "failed"
        if kind in ("done", "failed") and isinstance(total_ms, int) and total_ms >= 0:
            finished.append(total_ms)
            if index is not None:
                bins[index].durations[_band(total_ms)] += 1
                per_bin_ms.setdefault(index, []).append(total_ms)
    finished.sort()
    totals.p50_ms, totals.p95_ms = _percentile(finished, 0.5), _percentile(finished, 0.95)
    for index, ms in per_bin_ms.items():
        ms.sort()
        bins[index].p50_ms, bins[index].max_ms = _percentile(ms, 0.5), ms[-1]
    models: dict[int, dict[str, int]] = {}
    for item in items:
        index = slot(item[-1])
        if index is not None:
            bins[index].tokens_total += item[-2]
            if len(item) == 8:      # (scope, provider, model, tin, tout, est, total, ts)
                _, provider, model, tin, tout, est, total, _ = item
                if model:
                    per = models.setdefault(index, {})
                    per[model] = per.get(model, 0) + total
                usd = item_usd(model, tin, tout, est, provider)
                if usd is not None:
                    bins[index].usd = round((bins[index].usd or 0.0) + usd, 6)
    for index, per in models.items():
        bins[index].models = [{"model": m, "tokens": t} for m, t in
                              sorted(per.items(), key=lambda kv: kv[1], reverse=True)[:3]]
    return totals, bins



def item_usd(model: str | None, tokens_in: int | None, tokens_out: int | None,
             estimated: bool, provider: str | None = None) -> float | None:
    """USD for one run/ledger item, or None when it can't be known honestly.
    Estimated tokens are NEVER priced — even for a known-price model, and even when
    the sticky-estimated bucket left real-looking token fields behind. provider
    gates the local $0 table (review I1: hosted deepseek-r1 is paid, not free)."""
    if estimated:
        return None
    return prices.usd(model, tokens_in, tokens_out, provider=provider)


# Run.kind → usage scope. live and scheduled are ALWAYS included (Task-2 review I2:
# scheduled fires target real/dedicated conversations users open — unlike synthetic
# replay cids — so they count in BOTH the summary and the per-conversation view);
# replay stays behind the include_replay gate.
_KIND_SCOPES = {"live": "spawn", "host": "answer", "scheduled": "scheduled", "replay": "replay"}


async def fetch_usage_items(
    *, conversation_id: str | None = None, since: datetime | None = None,
    include_replay: bool = False,
) -> list[tuple]:
    """Runs (kind mapped per _KIND_SCOPES) + ledger rows, normalized to
    (scope, provider, model, tokens_in, tokens_out, estimated, tokens_total, ts)."""
    # kind='replay' → scope "replay" only on the fleet-wide card (evolution arms are
    # the single largest burner — omitting them would break the card's own "never
    # pretends full coverage" contract). Replay rows carry synthetic conversation
    # ids ("evolution-replay"), so per-conversation queries never see them.
    kinds = ("live", "host", "scheduled", "replay") if include_replay else ("live", "host", "scheduled")
    run_q = select(Run.kind, Run.provider, Run.model, Run.tokens_in, Run.tokens_out,
                   Run.tokens_estimated, Run.task_tokens, Run.created_at
                   ).where(Run.kind.in_(kinds))
    led_q = select(UsageLedger.scope, UsageLedger.provider, UsageLedger.model,
                   UsageLedger.tokens_in, UsageLedger.tokens_out,
                   UsageLedger.tokens_estimated, UsageLedger.tokens_total, UsageLedger.ts)
    if conversation_id is not None:
        run_q = run_q.where(Run.conversation_id == conversation_id)
        led_q = led_q.where(UsageLedger.conversation_id == conversation_id)
    if since is not None:
        run_q = run_q.where(Run.created_at >= since)
        led_q = led_q.where(UsageLedger.ts >= since)
    async with db_session.AsyncSessionLocal() as db:
        runs = (await db.execute(run_q)).all()
        ledger = (await db.execute(led_q)).all()
    items = [(_KIND_SCOPES.get(kind, kind),
              provider, model, tin, tout, bool(est), task_tokens or 0, ts)
             for (kind, provider, model, tin, tout, est, task_tokens, ts) in runs]
    items += [(scope, provider, model, tin, tout, bool(est), total or 0, ts)
              for (scope, provider, model, tin, tout, est, total, ts) in ledger]
    return items


@router.get("/usage/summary", response_model=UsageSummaryOut)
async def usage_summary(
    rng: str = Query("7d", alias="range", pattern="^(24h|7d|30d)$"),
) -> UsageSummaryOut:
    now = datetime.utcnow()
    since = now - _WINDOWS[rng]
    items = await fetch_usage_items(since=since, include_replay=True)
    async with db_session.AsyncSessionLocal() as db:
        run_rows = (await db.execute(
            select(Run.status, Run.total_ms, Run.created_at)
            .where(Run.kind.in_(_RUN_KINDS), Run.created_at >= since))).all()
    runs, bins = run_activity([tuple(r) for r in run_rows], items, since, now, rng)

    groups: dict[tuple, dict] = {}
    daily: dict[str, int] = {}
    for scope, provider, model, tin, tout, est, total, ts in items:
        g = groups.setdefault((provider, model, scope),
                              {"tokens_total": 0, "usd": None, "estimated_any": False})
        g["tokens_total"] += total
        g["estimated_any"] = g["estimated_any"] or est
        usd = item_usd(model, tin, tout, est, provider)
        if usd is not None:
            g["usd"] = (g["usd"] or 0.0) + usd
        if ts is not None:
            day = ts.date().isoformat()
            daily[day] = daily.get(day, 0) + total

    rows = [
        UsageSummaryRowOut(provider=provider, model=model, scope=scope, **agg)
        for (provider, model, scope), agg in sorted(
            groups.items(), key=lambda kv: kv[1]["tokens_total"], reverse=True)
    ]
    series = [UsageDailyPointOut(date=d, tokens_total=t) for d, t in sorted(daily.items())]
    priced = [r.usd for r in rows if r.usd is not None]
    return UsageSummaryOut(
        range=rng, rows=rows, daily=series, not_covered=NOT_COVERED,
        tokens_total=sum(r.tokens_total for r in rows),
        usd_total=round(sum(priced), 6) if priced else None,
        estimated_any=any(r.estimated_any for r in rows),
        runs=runs, bin_seconds=int(_BIN[rng].total_seconds()),
        duration_bands=[label for _, label in DURATION_BANDS], bins=bins)
