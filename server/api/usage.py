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

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from arslan.llm import prices
from server.auth import require_auth
from server.db import session as db_session
from server.db.models import Run, UsageLedger
from server.schemas import (
    UsageDailyPointOut,
    UsageSummaryOut,
    UsageSummaryRowOut,
)

router = APIRouter(dependencies=[Depends(require_auth)])

# LLM call sites NOT ledgered yet — mirrors spec §S3-D's 未计入清单 annotation
# (2026-07-11-s3-table-stakes-design.md). Update BOTH places when wiring a new scope.
NOT_COVERED = [
    "_route_announcement",
    "distill_service",
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
_KIND_SCOPES = {"live": "spawn", "scheduled": "scheduled", "replay": "replay"}


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
    kinds = ("live", "scheduled", "replay") if include_replay else ("live", "scheduled")
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
    items = await fetch_usage_items(since=datetime.utcnow() - _WINDOWS[rng], include_replay=True)

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
    return UsageSummaryOut(range=rng, rows=rows, daily=series, not_covered=NOT_COVERED)
