"""Read-only Run replay + evaluation endpoint."""
from __future__ import annotations

import asyncio
import bisect
import math
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import load_only
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.db.models import Run, RunEvaluation, RunStep
from server.run_kinds import USER_RUN_KINDS
from server.services import run_registry
from server.schemas import (
    AnomalyOut,
    CatalogFleetOut,
    CatalogSpawnOut,
    RunCatalogOut,
    RunDetailOut,
    RunEvaluationOut,
    RunListItemOut,
    RunOut,
    RunSpawnSummaryOut,
    RunStepOut,
    RunSummaryOut,
    RunTrendPointOut,
    TimelineCellOut,
    TimelineOut,
    TimelineSpawnOut,
    VitalsBucketOut,
    VitalsOut,
)

router = APIRouter(dependencies=[Depends(require_auth)])

# Judge dimensions, in display order (mirrors the frontend DIMENSION_LABELS).
DIMENSIONS = ("routing", "fabrication", "identity", "completion")

PASS_THRESHOLD = 7.0

# --- /runs/catalog thresholds ---------------------------------------------
ERR_RED, ERR_AMBER = 0.15, 0.05
SCORE_RED, SCORE_AMBER = 4.0, 7.0
PASS_RED = 50


def _window_start(rng: str) -> datetime | None:
    if rng == "1h":
        return datetime.utcnow() - timedelta(hours=1)
    if rng == "24h":
        return datetime.utcnow() - timedelta(hours=24)
    return None


# Duration heatmap bins (ms). Fixed thresholds — observational, not tied to scoring.
DURATION_EDGES = [0, 100, 500, 1000, 3000, 10000, math.inf]
DURATION_LABELS = ["<0.1s", "0.1–0.5s", "0.5–1s", "1–3s", "3–10s", ">10s"]


def _bucket_bounds(start: datetime | None, runs: list, n: int) -> list[datetime]:
    """n+1 evenly-spaced edges over [start (or earliest run), now]. range='all'
    (start is None) falls back to the earliest run's timestamp."""
    end = datetime.utcnow()
    if start is None:
        stamps = [r.created_at for r in runs if r.created_at]
        start = min(stamps) if stamps else end - timedelta(hours=1)
    if end <= start:
        end = start + timedelta(seconds=1)
    step = (end - start) / n
    return [start + step * i for i in range(n + 1)]


def _bucket_index(ts: datetime, edges: list[datetime]) -> int:
    """Bucket ts falls in, clamped to [0, len(edges)-2]."""
    for i in range(len(edges) - 1):
        if ts < edges[i + 1]:
            return i
    return len(edges) - 2


def _p95(values: list[int]) -> int | None:
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    idx = max(0, math.ceil(0.95 * len(xs)) - 1)
    return int(xs[idx])


def _health(error_ratio: float, avg_score: float | None, pass_rate: int | None) -> str:
    if error_ratio > ERR_RED or (avg_score is not None and avg_score < SCORE_RED) \
       or (pass_rate is not None and pass_rate < PASS_RED):
        return "red"
    if error_ratio > ERR_AMBER or (avg_score is not None and avg_score < SCORE_AMBER):
        return "amber"
    return "green"


_HEALTH_ORDER = {"red": 0, "amber": 1, "green": 2}


#: Browser previews run through host_run under this name (server/api/browser.py).
_BROWSER_RUN_NAME = "Browser preview"


async def run_origins(db: AsyncSession, runs: list[Run]) -> dict[int, str]:
    """Where each run came from, read from records that already exist (0.1.58 §7):
    a scheduled fire (Run.kind, or since C1 a host turn its scheduled_task_runs row names), a browser preview (its run name),
    a background job (its result message carries job_outcome), a message sent from the paired iPhone
    (the user message that started the turn has source="phone"); otherwise chat."""
    from server.db.models import ArslanMessage, ScheduledTaskRun
    out: dict[int, str] = {}
    pending: list[Run] = []
    fired = set((await db.execute(select(ScheduledTaskRun.run_id).where(
        ScheduledTaskRun.run_id.in_([r.id for r in runs])))).scalars()) if runs else set()
    for r in runs:
        if r.kind == "scheduled" or r.id in fired:
            out[r.id] = "scheduled"
        elif r.spawn_name == _BROWSER_RUN_NAME:
            out[r.id] = "browser"
        else:
            out[r.id] = "chat"
            pending.append(r)
    if not pending:
        return out
    ids = [r.id for r in pending]
    answers = (await db.execute(
        select(ArslanMessage.run_id, ArslanMessage.id, ArslanMessage.conversation_id, ArslanMessage.job_outcome)
        .where(ArslanMessage.run_id.in_(ids), ArslanMessage.role != "user"))).all()
    first_answer: dict[int, tuple[int, str]] = {}
    for run_id, msg_id, conv, job_outcome in answers:
        if job_outcome is not None:
            out[run_id] = "job"
        elif run_id not in first_answer or msg_id < first_answer[run_id][0]:
            first_answer[run_id] = (msg_id, conv)
    convs = {conv for _, conv in first_answer.values()}
    phoned = set((await db.execute(
        select(ArslanMessage.conversation_id).where(
            ArslanMessage.conversation_id.in_(convs), ArslanMessage.source == "phone").distinct())).scalars())
    asked = [(run_id, msg_id, conv) for run_id, (msg_id, conv) in first_answer.items()
             if out[run_id] == "chat" and conv in phoned]
    if not asked:
        return out
    # The user message that started each turn: the last one before its answer that was not read
    # mid-turn (K9b tags those with their run). Read once for all of them, not once per run: Progress's
    # axis asks for up to 200 runs every 30 seconds (INB7-b; ⓪Plan's review of PR 622).
    rows = (await db.execute(
        select(ArslanMessage.conversation_id, ArslanMessage.id, ArslanMessage.source).where(
            ArslanMessage.conversation_id.in_({conv for _, _, conv in asked}), ArslanMessage.role == "user",
            ArslanMessage.run_id.is_(None), ArslanMessage.id < max(msg_id for _, msg_id, _ in asked))
        .order_by(ArslanMessage.id))).all()
    asks: dict[str, tuple[list[int], list[str | None]]] = {}
    for conv, msg_id, source in rows:
        ids, sources = asks.setdefault(conv, ([], []))
        ids.append(msg_id)
        sources.append(source)
    for run_id, msg_id, conv in asked:
        ids, sources = asks.get(conv, ([], []))
        last = bisect.bisect_left(ids, msg_id) - 1
        if last >= 0 and sources[last] == "phone":
            out[run_id] = "phone"
    return out


#: INB7-c2: a phone turn is found from its messages, after the query, so the phone chip reads runs in batches this big until a page
#: is full.
_PHONE_BATCH = 200


def _scoped(since: datetime | None, until: datetime | None, model: str | None):
    """The runs the list may show (user kinds, newest first) within a span and a model."""
    # E2: replay runs (kind='replay') are the gate's internal two-arm evidence — they never
    # surface in the runs list. get_run detail stays unfiltered so the card can link into a
    # specific replay run's trace. 0.1.58: scheduled fires are listed too — Activity's tiles
    # already counted them, the list beneath silently did not.
    q = select(Run).where(Run.kind.in_(USER_RUN_KINDS)).order_by(Run.id.desc())
    # Stored times are naive UTC; an aware bound is converted, never compared raw.
    if since is not None:
        q = q.where(Run.created_at >= _naive_utc(since))
    if until is not None:
        q = q.where(Run.created_at < _naive_utc(until))
    if model:
        q = q.where(Run.model == model)
    return q


def _asking() -> set[str]:
    """INB7-b: the conversations with a card open, the same live list progress.waiting_reasons reads."""
    from server.services import approvals
    return {card["conversation_id"] for card in approvals.all_pending() if card.get("conversation_id")}


def _phoned():
    """The conversations a phone message ever reached: the only ones a phone turn can be in."""
    from server.db.models import ArslanMessage
    return select(ArslanMessage.conversation_id).where(ArslanMessage.source == "phone").distinct()


def _chip(q, outcome: str | None, origin: str | None, asking: set[str]):
    """INB7-c2, board F's chips: 「失败」 and 「要你做」 (outcome), 「定时」 and 「手机」 (origin). 「手机」 only narrows to the conversations a phone
    message reached; which of their turns came from the phone is read after the query (run_origins)."""
    if outcome == "failed":
        q = q.where(Run.status == "failed")
    elif outcome == "waiting":
        q = q.where(Run.status == "recording", Run.conversation_id.in_(asking))
    if origin == "scheduled":
        # Since C1 (0.1.63) a fire is a host turn, linked only by scheduled_task_runs.run_id (scheduler.py); older ones kept
        # kind "scheduled" (⓪Plan's review of PR 627).
        from server.db.models import ScheduledTaskRun
        fired = select(ScheduledTaskRun.run_id).where(ScheduledTaskRun.run_id.is_not(None))
        q = q.where(or_(Run.kind == "scheduled", Run.id.in_(fired)))
    elif origin == "phone":
        q = q.where(Run.conversation_id.in_(_phoned()))
    return q


async def _phone_turns(db: AsyncSession, q, limit: int | None) -> tuple[list[Run], dict[int, str]]:
    """The phone chip's runs: read in batches, newest first, keeping those that came from the phone, until `limit` are found
    (None: all of them, for the count)."""
    found: list[Run] = []
    origins: dict[int, str] = {}
    cursor: int | None = None
    while limit is None or len(found) < limit:
        batch = list((await db.execute((q if cursor is None else q.where(Run.id < cursor)).limit(_PHONE_BATCH))).scalars())
        if not batch:
            break
        seen = await run_origins(db, batch)
        origins.update(seen)
        found += [r for r in batch if seen.get(r.id) == "phone"]
        cursor = batch[-1].id
        if len(batch) < _PHONE_BATCH:
            break
    return (found if limit is None else found[:limit]), origins


@router.get("/runs", response_model=list[RunListItemOut])
async def list_runs(
    spawn_id: int | None = None,
    conversation_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, ge=1),
    since: datetime | None = None,
    until: datetime | None = None,
    model: str | None = Query(None, max_length=200),
    outcome: Literal["failed", "waiting"] | None = None,
    origin: Literal["scheduled", "phone"] | None = None,
    db: AsyncSession = Depends(get_session),
) -> list[RunListItemOut]:
    asking = _asking()
    q = _chip(_scoped(since, until, model), outcome, origin, asking)
    if spawn_id is not None:
        q = q.where(Run.spawn_id == spawn_id)
    if conversation_id is not None:
        q = q.where(Run.conversation_id == conversation_id)
    if before_id is not None:
        q = q.where(Run.id < before_id)
    if origin == "phone":
        rows, origins = await _phone_turns(db, q, limit)
    else:
        rows = list((await db.execute(q.limit(limit))).scalars().all())
        origins = await run_origins(db, rows)
    return [
        RunListItemOut(
            id=r.id, spawn_id=r.spawn_id, spawn_name=r.spawn_name, status=r.status,
            overall_score=r.overall_score, overall_badge=r.overall_badge,
            total_ms=r.total_ms, user_message=r.user_message,
            created_at=r.created_at.isoformat() if r.created_at else None,
            origin=origins.get(r.id, "chat"), model=r.model, tokens=r.task_tokens or None,
            waiting=r.status == "recording" and r.conversation_id in asking,
            ended_at=r.ended_at.isoformat() if r.ended_at else None,
        )
        for r in rows
    ]


# NOTE: must stay registered BEFORE /runs/{run_id} (path-param collision).
@router.get("/runs/counts")
async def run_counts(
    since: datetime | None = None,
    until: datetime | None = None,
    model: str | None = Query(None, max_length=200),
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """INB7-c2: how many runs each of board F's chips would list, in the same span and model as the list."""
    asking = _asking()
    scope = _scoped(since, until, model)

    async def count(q) -> int:
        return int((await db.execute(select(func.count()).select_from(q.order_by(None).subquery()))).scalar() or 0)

    # Only what run_origins reads, not whole rows: the count may walk every phone turn in the span.
    lean = _chip(scope, None, "phone", asking).options(load_only(Run.id, Run.kind, Run.spawn_name, Run.conversation_id))
    phone, _ = await _phone_turns(db, lean, None)
    return {"waiting": await count(_chip(scope, "waiting", None, asking)), "failed": await count(_chip(scope, "failed", None, asking)),
            "scheduled": await count(_chip(scope, None, "scheduled", asking)), "phone": len(phone)}


def _naive_utc(ts: datetime) -> datetime:
    from datetime import timezone
    return ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts


# NOTE: must stay registered BEFORE /runs/{run_id}, or FastAPI tries to parse
# "summary" as an int path param (422).
@router.get("/runs/summary", response_model=RunSummaryOut)
async def runs_summary(db: AsyncSession = Depends(get_session)) -> RunSummaryOut:
    scored = (Run.status == "scored", Run.overall_score.isnot(None))

    scored_count, avg_score = (await db.execute(
        select(func.count(Run.id), func.avg(Run.overall_score)).where(*scored)
    )).one()
    pass_count = (await db.execute(
        select(func.count(Run.id)).where(*scored, Run.overall_score >= PASS_THRESHOLD)
    )).scalar_one()
    pass_rate = round(pass_count / scored_count * 100) if scored_count else None

    dim_rows = (await db.execute(
        select(RunEvaluation.dimension, func.avg(RunEvaluation.score))
        .join(Run, Run.id == RunEvaluation.run_id)
        .where(*scored)
        .group_by(RunEvaluation.dimension)
    )).all()
    dimension_averages: dict[str, float | None] = {d: None for d in DIMENSIONS}
    for dim, avg in dim_rows:
        if dim in dimension_averages and avg is not None:
            dimension_averages[dim] = round(float(avg), 2)

    spawn_rows = (await db.execute(
        select(
            Run.spawn_name,
            func.count(Run.id),
            func.avg(Run.overall_score),
            func.sum(case((Run.overall_score >= PASS_THRESHOLD, 1), else_=0)),
        )
        .where(*scored, Run.spawn_name.isnot(None))
        .group_by(Run.spawn_name)
        .order_by(func.count(Run.id).desc())
    )).all()
    per_spawn = [
        RunSpawnSummaryOut(
            spawn_name=name,
            scored_count=cnt,
            avg_score=round(float(avg), 2) if avg is not None else None,
            pass_rate=round((passed or 0) / cnt * 100) if cnt else None,
        )
        for name, cnt, avg, passed in spawn_rows
    ]

    recent_rows = (await db.execute(
        select(Run.id, Run.overall_score, Run.created_at)
        .order_by(Run.id.desc())
        .limit(50)
    )).all()
    recent = [
        RunTrendPointOut(
            id=rid, overall_score=score,
            created_at=created.isoformat() if created else None,
        )
        for rid, score, created in reversed(recent_rows)
    ]

    return RunSummaryOut(
        scored_count=scored_count,
        avg_score=round(float(avg_score), 2) if avg_score is not None else None,
        pass_rate=pass_rate,
        dimension_averages=dimension_averages,
        per_spawn=per_spawn,
        recent=recent,
    )


# NOTE: must stay registered BEFORE /runs/{run_id}, or FastAPI tries to parse
# "catalog" as an int path param (422).
N_CATALOG_TREND = 12


@router.get("/runs/catalog", response_model=RunCatalogOut)
async def runs_catalog(rng: str = Query("1h", alias="range"),
                       db: AsyncSession = Depends(get_session)) -> RunCatalogOut:
    start = _window_start(rng)
    q = select(Run).where(Run.kind.in_(USER_RUN_KINDS))  # E2: replay runs never surface in diagnosis
    if start is not None:
        q = q.where(Run.created_at >= start)
    runs = (await db.execute(q.order_by(Run.created_at))).scalars().all()
    edges = _bucket_bounds(start, runs, N_CATALOG_TREND)

    by_spawn: dict[int | None, list[Run]] = {}
    for r in runs:
        by_spawn.setdefault(r.spawn_id, []).append(r)

    spawns: list[CatalogSpawnOut] = []
    for sid, rs in by_spawn.items():
        n = len(rs)
        errs = sum(1 for r in rs if r.error_kind)
        scored = [r.overall_score for r in rs if r.status == "scored" and r.overall_score is not None]
        passed = sum(1 for s in scored if s >= PASS_THRESHOLD)
        avg = round(sum(scored) / len(scored), 2) if scored else None
        pass_rate = round(passed / len(scored) * 100) if scored else None
        error_ratio = round(errs / n, 4) if n else 0.0
        trend = [round(s, 2) for s in scored][-8:]
        # Per-bucket sparkline trends (12 buckets over the window).
        lat_buckets: list[list[int]] = [[] for _ in range(N_CATALOG_TREND)]
        err_buckets = [0] * N_CATALOG_TREND
        cnt_buckets = [0] * N_CATALOG_TREND
        for r in rs:
            if not r.created_at:
                continue
            b = _bucket_index(r.created_at, edges)
            cnt_buckets[b] += 1
            if r.error_kind:
                err_buckets[b] += 1
            if r.total_ms is not None:
                lat_buckets[b].append(r.total_ms)
        latency_trend = [_p95(v) for v in lat_buckets]
        error_trend = [round(e / c, 4) if c else 0.0 for e, c in zip(err_buckets, cnt_buckets)]
        spawns.append(CatalogSpawnOut(
            spawn_id=sid,
            spawn_name=next((r.spawn_name for r in reversed(rs) if r.spawn_name), None),
            model=next((r.model for r in reversed(rs) if r.model), None),
            run_count=n, error_ratio=error_ratio,
            p95_ms=_p95([r.total_ms for r in rs]), pass_rate=pass_rate, avg_score=avg,
            tokens_sum=sum(r.task_tokens or 0 for r in rs),
            health=_health(error_ratio, avg, pass_rate), score_trend=trend,
            latency_trend=latency_trend, error_trend=error_trend, rate_trend=cnt_buckets,
        ))
    spawns.sort(key=lambda s: (_HEALTH_ORDER.get(s.health, 3), -s.error_ratio))

    all_scored = [r.overall_score for r in runs if r.status == "scored" and r.overall_score is not None]
    fleet = CatalogFleetOut(
        run_count=len(runs),
        error_ratio=round(sum(1 for r in runs if r.error_kind) / len(runs), 4) if runs else 0.0,
        p95_ms=_p95([r.total_ms for r in runs]),
        pass_rate=round(sum(1 for s in all_scored if s >= PASS_THRESHOLD) / len(all_scored) * 100) if all_scored else None,
        tokens_sum=sum(r.task_tokens or 0 for r in runs),
    )
    return RunCatalogOut(range=rng, fleet=fleet, spawns=spawns)


N_VITALS_BUCKETS = 30


# NOTE: must stay registered BEFORE /runs/{run_id} (path-param collision).
@router.get("/runs/vitals", response_model=VitalsOut)
async def runs_vitals(rng: str = Query("1h", alias="range"),
                      db: AsyncSession = Depends(get_session)) -> VitalsOut:
    start = _window_start(rng)
    q = select(Run).where(Run.kind.in_(USER_RUN_KINDS))  # E2: replay runs never surface in diagnosis
    if start is not None:
        q = q.where(Run.created_at >= start)
    runs = (await db.execute(q.order_by(Run.created_at))).scalars().all()
    edges = _bucket_bounds(start, runs, N_VITALS_BUCKETS)
    counts = [0] * N_VITALS_BUCKETS
    errors = [0] * N_VITALS_BUCKETS
    matrix = [[0] * N_VITALS_BUCKETS for _ in DURATION_LABELS]
    for r in runs:
        if not r.created_at:
            continue
        b = _bucket_index(r.created_at, edges)
        counts[b] += 1
        if r.error_kind:
            errors[b] += 1
        ms = r.total_ms or 0
        for di in range(len(DURATION_LABELS)):
            if DURATION_EDGES[di] <= ms < DURATION_EDGES[di + 1]:
                matrix[di][b] += 1
                break
    total = len(runs)
    step_ms = int((edges[1] - edges[0]).total_seconds() * 1000) if len(edges) > 1 else 0
    return VitalsOut(
        range=rng, bucket_ms=step_ms, total=total,
        error_ratio=round(sum(errors) / total, 4) if total else 0.0,
        p95_ms=_p95([r.total_ms for r in runs]),
        buckets=[VitalsBucketOut(t=edges[i].isoformat(), count=counts[i], errors=errors[i])
                 for i in range(N_VITALS_BUCKETS)],
        duration_bins=list(DURATION_LABELS),
        duration_matrix=matrix,
    )


# NOTE: must stay registered BEFORE /runs/{run_id}, or FastAPI tries to parse
# "anomalies" as an int path param (422).
@router.get("/runs/anomalies", response_model=list[AnomalyOut])
async def runs_anomalies(range: str = Query("1h"),
                         db: AsyncSession = Depends(get_session)) -> list[AnomalyOut]:
    start = _window_start(range)
    q = select(Run).where(Run.kind.in_(USER_RUN_KINDS))  # E2: replay runs never surface in diagnosis
    if start is not None:
        q = q.where(Run.created_at >= start)
    runs = (await db.execute(q.order_by(Run.created_at))).scalars().all()
    by_spawn: dict[int | None, list[Run]] = {}
    for r in runs:
        by_spawn.setdefault(r.spawn_id, []).append(r)

    run_ids = [r.id for r in runs]
    fail_dims: dict[int, set[str]] = {}
    if run_ids:
        for rid, dim in (await db.execute(
            select(RunEvaluation.run_id, RunEvaluation.dimension)
            .where(RunEvaluation.run_id.in_(run_ids), RunEvaluation.status == "fail")
        )).all():
            fail_dims.setdefault(rid, set()).add(dim)

    out: list[AnomalyOut] = []
    for sid, rs in by_spawn.items():
        name = next((r.spawn_name for r in reversed(rs) if r.spawn_name), None)
        n = len(rs)
        errs = [r for r in rs if r.error_kind]
        err_ratio = len(errs) / n if n else 0.0
        since0 = errs[0].created_at.isoformat() if errs and errs[0].created_at else None
        if n >= 3 and err_ratio > ERR_RED:
            out.append(AnomalyOut(severity="red", kind="error_rate", spawn_id=sid, spawn_name=name,
                title_key="anomaly.error_rate.high", detail_key="anomaly.error_rate.detail",
                params={"pct": round(err_ratio * 100), "errs": len(errs), "n": n}, since=since0))
        elif n >= 3 and err_ratio > ERR_AMBER:
            out.append(AnomalyOut(severity="amber", kind="error_rate", spawn_id=sid, spawn_name=name,
                title_key="anomaly.error_rate.rising", detail_key="anomaly.error_rate.pct_only",
                params={"pct": round(err_ratio * 100)}, since=since0))
        for dim in DIMENSIONS:
            streak = 0
            first_ts = None
            for r in rs:
                if dim in fail_dims.get(r.id, set()):
                    streak += 1
                    first_ts = first_ts or (r.created_at.isoformat() if r.created_at else None)
                    if streak >= 2:
                        out.append(AnomalyOut(severity="red", kind="fabrication" if dim == "fabrication" else dim,
                            spawn_id=sid, spawn_name=name, title_key="anomaly.dim_streak.title",
                            detail_key="anomaly.dim_streak.detail", params={"dim": dim, "streak": streak},
                            since=first_ts, run_id=r.id))
                        break
                else:
                    streak = 0
                    first_ts = None
        scored = [r.overall_score for r in rs if r.status == "scored" and r.overall_score is not None]
        if len(scored) >= 3:
            pr = round(sum(1 for s in scored if s >= PASS_THRESHOLD) / len(scored) * 100)
            if pr < PASS_RED:
                out.append(AnomalyOut(severity="amber", kind="pass_rate", spawn_id=sid, spawn_name=name,
                    title_key="anomaly.pass_rate.low", detail_key="anomaly.pass_rate.detail",
                    params={"pct": pr}, since=None))

    if run_ids:
        for rid, ref in (await db.execute(
            select(RunStep.run_id, RunStep.ref).where(RunStep.run_id.in_(run_ids), RunStep.kind == "tool_call")
        )).all():
            if isinstance(ref, dict) and ref.get("ok") is False:
                rn = next((r for r in runs if r.id == rid), None)
                out.append(AnomalyOut(severity="amber", kind="tool_error",
                    spawn_id=rn.spawn_id if rn else None, spawn_name=(rn.spawn_name if rn else None),
                    title_key="anomaly.tool_error.title", detail_key="anomaly.tool_error.detail",
                    params={"tool": ref.get("tool", "tool"), "run_id": rid},
                    since=(rn.created_at.isoformat() if rn and rn.created_at else None), run_id=rid))
                break
    out.sort(key=lambda a: 0 if a.severity == "red" else 1)
    return out


N_TIMELINE_BUCKETS = 24


# NOTE: must stay registered BEFORE /runs/{run_id} (path-param collision).
@router.get("/runs/timeline", response_model=TimelineOut)
async def runs_timeline(rng: str = Query("1h", alias="range"),
                        db: AsyncSession = Depends(get_session)) -> TimelineOut:
    start = _window_start(rng)
    q = select(Run).where(Run.kind.in_(USER_RUN_KINDS))  # E2: replay runs never surface in diagnosis
    if start is not None:
        q = q.where(Run.created_at >= start)
    runs = (await db.execute(q.order_by(Run.created_at))).scalars().all()
    edges = _bucket_bounds(start, runs, N_TIMELINE_BUCKETS)
    by_spawn: dict[int | None, list[Run]] = {}
    for r in runs:
        by_spawn.setdefault(r.spawn_id, []).append(r)

    spawns: list[TimelineSpawnOut] = []
    for sid, rs in by_spawn.items():
        buckets: list[list[Run]] = [[] for _ in range(N_TIMELINE_BUCKETS)]
        for r in rs:
            if r.created_at:
                buckets[_bucket_index(r.created_at, edges)].append(r)
        cells: list[TimelineCellOut] = []
        for b in buckets:
            if not b:
                cells.append(TimelineCellOut(sev="none", count=0, errors=0))
                continue
            errs = sum(1 for r in b if r.error_kind)
            scored = [r.overall_score for r in b if r.status == "scored" and r.overall_score is not None]
            avg = sum(scored) / len(scored) if scored else None
            pr = round(sum(1 for s in scored if s >= PASS_THRESHOLD) / len(scored) * 100) if scored else None
            cells.append(TimelineCellOut(sev=_health(errs / len(b), avg, pr), count=len(b), errors=errs))
        spawns.append(TimelineSpawnOut(
            spawn_id=sid,
            spawn_name=next((r.spawn_name for r in reversed(rs) if r.spawn_name), None),
            cells=cells))
    spawns.sort(key=lambda s: (-sum(c.sev == "red" for c in s.cells),
                               -sum(c.sev == "amber" for c in s.cells)))
    return TimelineOut(range=rng, buckets=[e.isoformat() for e in edges[:-1]], spawns=spawns)


# Registered BEFORE /runs/{run_id} (codebase convention for the catch-all gotcha).
@router.get("/runs/{run_id}/artifacts")
async def list_run_artifacts(run_id: int, db: AsyncSession = Depends(get_session)) -> list[dict]:
    from server.services import artifact_store
    if await db.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return artifact_store.list_artifacts(run_id)


@router.get("/runs/{run_id}/artifacts/{filename}")
async def download_run_artifact(run_id: int, filename: str) -> FileResponse:
    """Serve an HTML deliverable stored by the spawn-output artifact channel (HX-2).

    Acceptance #3: after display_content is summarized, the full document stays
    retrievable from here. The filename is strictly validated: it must belong to THIS
    run (run_{id}_ prefix) and contain no separators or dot-dot — traversal rejected.
    """
    from server.services import artifact_store

    if not artifact_store.safe_filename(run_id, filename):
        raise HTTPException(status_code=400, detail="invalid artifact filename")
    path = artifact_store.root() / filename
    if path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, media_type="application/octet-stream", filename=filename,
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "sandbox"})


@router.get("/runs/{run_id}/process")
async def run_process(run_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    """0.1.58 §1: what a reply did, in order and in plain data — the list under its footer.
    Raw input/output only with 设置 › 通用 › 显示技术细节 on."""
    from server.services import run_process as rp, settings_service
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "run_not_found"})
    steps = (await db.execute(select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq))).scalars().all()
    raw = (await settings_service._get_raw(db, "show_technical_details")) == "true"
    summary = (await rp.summaries(db, [run_id])).get(run_id, {})
    # INB7-b: when the run ran, so Progress's replay can place each step (entries carry `at`) on its own span. INB7-c3: its
    # conversation, whose changes (GET /conversations/{id}/changes) the inspector's 「改动」 reads.
    return {"run_id": run_id, "status": run.status, "conversation_id": run.conversation_id, **summary,
            "started_at": rp.utc(run.started_at),
            "ended_at": rp.utc(run.ended_at), "entries": rp.entries(list(steps), raw=raw)}


class CheckpointRestoreIn(BaseModel):
    what: Literal["files", "conversation", "both"]
    #: S3b: the newest message the box showed; the conversation is taken back only if it hasn't moved on.
    last_message_id: int | None = None

    @model_validator(mode="after")
    def _shown_range(self):
        if self.what != "files" and self.last_message_id is None:
            raise ValueError("last_message_id is required to take a conversation back")
        return self


class _FilesFailed(Exception):
    """S3b "both": some files could not be put back; the conversation stays, so the files can be tried again."""

    def __init__(self, files: dict) -> None:
        super().__init__("files_failed")
        self.files = files


def _started(run: Run) -> float:
    return run.started_at.replace(tzinfo=timezone.utc).timestamp() - 1


@router.get("/runs/{run_id}/checkpoint")
async def run_checkpoint(run_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    """0.1.63 S3: whether this run's file changes can be undone, and what an undo covers and does not;
    S3b: whether its conversation can (`conversation`, or `reason` why not), how many messages and later
    turns that removes, and how many facts."""
    from server.services import checkpoints, turn_undo
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "run_not_found"})
    return {**checkpoints.summary(run_id, _started(run)), **await turn_undo.preview(run_id)}


#: INB7-c3: the tools whose first call in a run saves its folder (checkpoints: write_file, edit_file, run_command).
_SAVING_TOOLS = ("write_file", "edit_file", "run_command")


@router.get("/runs/{run_id}/changes")
async def run_changes(run_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    """INB7-c3: what this one run changed in the user's folders, for Progress's 「改动」, from its own checkpoint manifest only
    (⓪Plan's review of PR 629: not a scan of its conversation). `state`:
    - `running`: it has not ended, so nothing is final;
    - `finishing`: it ended, but how it left a saved folder is not recorded yet (checkpoints.finish runs after);
    - `kept`: the paths an undo can still take back (the list WB1-3 shows), and whether it was undone;
    - `none`: nothing to list (it never saved a folder, or saved one and changed nothing in it);
    - `expired`: it called a tool that saves the folder, but its copy is gone (KEEP_S or the quota) or is an earlier run's;
    - `not_saved`: no folder could be saved (too many files, too little disk, another volume).
    Read only."""
    from server.services import checkpoints
    run = await db.get(Run, run_id)
    if run is None or run.kind not in USER_RUN_KINDS:
        raise HTTPException(404, detail={"code": "run_not_found"})
    base = {"undone": False, "paths": [], "conversation_id": run.conversation_id}
    if run.status == "recording":
        return {"state": "running", **base}
    not_before = _started(run)

    def read() -> tuple[str, dict]:
        data = checkpoints.manifest(run_id)
        if data is None or data["created_at"] < not_before:
            return "missing", {}
        roots = data.get("roots") or []
        if roots and all(entry.get("skipped") for entry in roots):
            return "not_saved", {}
        if any(entry.get("skipped") is None and entry.get("finished") is None for entry in roots):
            return "finishing", {}
        found = checkpoints.changes(run_id, not_before) or {"paths": [], "undone": False}
        return ("kept" if found["paths"] else "none"), found
    state, found = await asyncio.to_thread(read)
    if state == "missing":
        tools = (await db.execute(select(RunStep.ref).where(RunStep.run_id == run_id, RunStep.kind == "tool_call"))).scalars()
        state = "expired" if any(isinstance(ref, dict) and ref.get("tool") in _SAVING_TOOLS for ref in tools) else "none"
    if state == "kept":
        return {"state": "kept", "undone": found["undone"], "paths": found["paths"], "conversation_id": run.conversation_id}
    return {"state": state, **base}


@router.get("/conversations/{conversation_id}/changes")
async def conversation_changes(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """WB1-3: what each turn of this conversation changed in the user's folders, newest turn first, path by
    path (made, edited, deleted), for Overview's Changes. Only turns whose checkpoint is still kept, which is
    the set an undo can take back (checkpoints.changes); a turn that changed nothing is left out. Read only.
    The runs are this conversation's own, as the runs list filters them (live, host, scheduled)."""
    from server.db.models import ArslanMessage
    from server.services import checkpoints
    runs = (await db.execute(select(Run).where(Run.conversation_id == conversation_id,
                                               Run.kind.in_(USER_RUN_KINDS))
                             .order_by(Run.id.desc()).limit(200))).scalars().all()
    if not runs and (await db.execute(select(ArslanMessage.id).where(
            ArslanMessage.conversation_id == conversation_id).limit(1))).first() is None:
        raise HTTPException(404, detail={"code": "conversation_not_found"})
    wanted = [(run.id, _started(run), run.started_at) for run in runs]

    def read() -> list[dict]:                 # file reads, one manifest per run: off the event loop (②Main)
        turns = []
        for run_id, not_before, started in wanted:
            found = checkpoints.changes(run_id, not_before)
            if not found or not found["paths"]:
                continue
            turns.append({"run_id": run_id,
                          "at": started.replace(tzinfo=timezone.utc).isoformat() if started else None,
                          "undone": found["undone"], "paths": found["paths"]})
        return turns
    return {"turns": await asyncio.to_thread(read)}


@router.get("/conversations/{conversation_id}/changes/{run_id}/diff")
async def conversation_change_diff(conversation_id: str, run_id: int, folder: str = Query(..., max_length=4096),
                                   path: str = Query(..., max_length=4096),
                                   db: AsyncSession = Depends(get_session)) -> dict:
    """DIFF1: one changed path of one turn as a line diff, the saved copy against the file now, for the
    reader opened from Overview's Changes. The run must be this conversation's (as `changes` lists them)
    and the path one `changes` lists for it; the folder must be one the reader may read
    (file_reader.roots). 404 `not_listed` otherwise, or once the checkpoint is gone; 403 `hidden` for a
    dot-path or a secret-shaped name; 200 with `reason` (`too_big`, `not_text`, `copy_changed`) and no
    lines when there is no diff to show. Read only."""
    from server.services import checkpoints, file_reader
    run = await db.get(Run, run_id)
    if run is None or run.conversation_id != conversation_id or run.kind not in ("live", "host", "scheduled"):
        raise HTTPException(404, detail={"code": "not_listed"})
    readable = await file_reader.roots()
    try:
        return {"reason": None, **await asyncio.to_thread(checkpoints.diff, run_id, _started(run), folder, path,
                                                          readable)}
    except checkpoints.NoDiff as exc:
        if exc.code == "not_listed":
            raise HTTPException(404, detail={"code": "not_listed"}) from None
        if exc.code == "hidden":
            raise HTTPException(403, detail={"code": "hidden"}) from None
        return {"reason": exc.code, "kind": None, "added": 0, "removed": 0, "since": False, "lines": []}


async def _repo_of(db: AsyncSession, conversation_id: str):
    """DIFF2: the conversation's folder (its project's, else the workspace, as /files/home) and the repo it is in."""
    from pathlib import Path
    from server.db.companion_models import ConversationContext, Project
    from server.services import git_changes, settings_service
    folder = None
    ctx = await db.get(ConversationContext, conversation_id)
    if ctx is not None and ctx.project_id:
        project = await db.get(Project, ctx.project_id)
        raw = (project.workspace_ref or "").strip() if project is not None else ""
        if raw and Path(raw).expanduser().is_dir():
            folder = Path(raw).expanduser().resolve()
    if folder is None:
        ws = await settings_service.workspace_dir(db)
        folder = ws.resolve() if ws else None
    root = git_changes.repo_root(folder, Path.home().resolve()) if folder else None
    return root, folder


@router.get("/conversations/{conversation_id}/repo-changes")
async def conversation_repo_changes(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """DIFF2-1: when the conversation's folder is in a git repo, the branch against its base, its commits, the files
    changed since the branch left the base (committed or not) and the branch's PRs (`signed_in` False without a
    signed-in `gh`); `{"repo": None}` otherwise, and Overview keeps DIFF1's per-turn list. Read only."""
    from server.services import git_changes
    root, folder = await _repo_of(db, conversation_id)
    if root is None:
        return {"repo": None}
    try:
        data = await asyncio.to_thread(git_changes.summary, root, folder)
        slug = await asyncio.to_thread(git_changes.github_repo, root)
    except git_changes.GitError as exc:   # no git (or macOS's shim), or a repo git refuses (safe.directory)
        return {"repo": {"error": "no_git" if str(exc) == "no git" else "unreadable"}}
    if slug is None:
        pulls = {"signed_in": None, "prs": [], "github": None}
    elif data["branch"] is None:
        pulls = {"signed_in": None, "prs": [], "github": slug}
    else:
        found = await asyncio.to_thread(git_changes.prs, slug, data["branch"])
        # gh's own error is `prs_error`, apart from `error` (git missing or refusing the repo).
        pulls = {"signed_in": found["signed_in"], "prs": found["prs"], "github": slug,
                 **({"prs_error": found["error"]} if "error" in found else {})}
    return {"repo": {**data, **pulls}}


@router.get("/conversations/{conversation_id}/repo-changes/diff")
async def conversation_repo_diff(conversation_id: str, path: str = Query(..., max_length=4096),
                                 db: AsyncSession = Depends(get_session)) -> dict:
    """DIFF2-1: one changed path of the repo as DIFF1's lines (the merge base's blob against the file now). 404
    `not_listed` for a path not among the changed ones; 403 `hidden` for a secret-shaped name; 200 with `reason`
    (`too_big`, `not_text`, `lfs`) and no lines when there is no diff to show. Read only."""
    from server.services import checkpoints, git_changes
    root, folder = await _repo_of(db, conversation_id)
    if root is None:
        raise HTTPException(404, detail={"code": "not_listed"})
    try:
        return {"reason": None, **await asyncio.to_thread(git_changes.file_diff, root, folder, path)}
    except git_changes.GitError:
        raise HTTPException(404, detail={"code": "not_listed"}) from None
    except checkpoints.NoDiff as exc:
        if exc.code == "not_listed":
            raise HTTPException(404, detail={"code": "not_listed"}) from None
        if exc.code == "hidden":
            raise HTTPException(403, detail={"code": "hidden"}) from None
        return {"reason": exc.code, "kind": None, "added": 0, "removed": 0, "since": False, "lines": []}


async def _with_history(undone: dict) -> dict:
    """The conversation as it is now, in the rows the window's socket sends, so the window shows it at once."""
    from server.ws.arslan import _history
    return {**undone, "history": await _history(undone["conversation_id"])}


def _refused(exc) -> HTTPException:
    return HTTPException(404 if exc.code == "none" else 409,
                         detail={"code": exc.code, "runs": getattr(exc, "runs", [])})


@router.post("/runs/{run_id}/checkpoint/restore")
async def restore_run_checkpoint(run_id: int, body: CheckpointRestoreIn,
                                 db: AsyncSession = Depends(get_session)) -> dict:
    """0.1.63 S3: put the run's files back ("files"), take its conversation back ("conversation", S3b),
    or both: every check of both first, so a refusal of either changes nothing; then the files, then the
    conversation, under the conversation's turn lock. A file that could not be put back keeps the
    conversation (409 files_failed with what was done; ⓪Plan's review 🟠4); a conversation that fails after
    the files went back is reported with them (409 conversation_failed, 🟡13)."""
    from server.services import checkpoints, turn_undo
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, detail={"code": "run_not_found"})
    files = body.what in ("files", "both")
    if files and not checkpoints.summary(run_id, _started(run))["exists"]:
        raise HTTPException(404, detail={"code": "none"})
    try:
        if body.what == "files":
            return await checkpoints.restore_files(run_id)
        if body.what == "conversation":
            return {"conversation": await _with_history(await turn_undo.undo(run_id, last=body.last_message_id))}

        async def files_first() -> dict:
            out = await checkpoints.restore_files(run_id)
            if any(r["failed"] or r.get("git") == "failed" for r in out["runs"]):
                raise _FilesFailed(out)
            return out
        await checkpoints.check_restore(run_id)          # the files' checks first, then the conversation's
        both = await turn_undo.undo(run_id, last=body.last_message_id, first=files_first)
    except (checkpoints.Refused, turn_undo.Refused) as exc:
        raise _refused(exc) from None
    except _FilesFailed as exc:
        raise HTTPException(409, detail={"code": "files_failed", "files": exc.files}) from None
    except turn_undo.PartlyDone as exc:
        raise HTTPException(409, detail={"code": "conversation_failed", "reason": exc.code,
                                         "files": exc.files}) from None
    files_out = both.pop("files")
    return {"files": files_out, "conversation": await _with_history(both)}


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: int, db: AsyncSession = Depends(get_session)) -> RunDetailOut:
    from server.services import artifact_store
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    steps = (await db.execute(
        select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.seq)
    )).scalars().all()
    evals = (await db.execute(
        select(RunEvaluation).where(RunEvaluation.run_id == run_id)
    )).scalars().all()

    return RunDetailOut(
        artifacts=artifact_store.list_artifacts(run_id),
        run=RunOut(
            no_learning=bool(run.no_learning),
            execution_budget=run.execution_budget,
            id=run.id, conversation_id=run.conversation_id, spawn_id=run.spawn_id,
            spawn_name=run.spawn_name, user_message=run.user_message, total_ms=run.total_ms,
            task_tokens=run.task_tokens, status=run.status,
            overall_score=run.overall_score, overall_badge=run.overall_badge,
            model=run.model, provider=run.provider,
            tokens_in=run.tokens_in, tokens_out=run.tokens_out,
            tokens_estimated=run.tokens_estimated,
            error_kind=run.error_kind, error_text=run.error_text,
            system_prompt=run.system_prompt, injected_kb=run.injected_kb,
            injected_kb_sources=run.injected_kb_sources,
            final_output=run.final_output,
        ),
        steps=[RunStepOut(seq=s.seq, kind=s.kind, ref=s.ref or {}, detail=s.detail or {},
                          duration_ms=s.duration_ms) for s in steps],
        evaluations=[RunEvaluationOut(dimension=e.dimension, status=e.status,
                                      score=e.score, comment=e.comment) for e in evals],
    )


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    """Cancel an in-flight run (S3-M1). 202 on cancel; 409 terminal; 404 unknown.

    The registry is process-local: a live run is only cancellable in the process
    executing it. When the registry misses, the DB row disambiguates 404 vs 409.
    """
    from server.services import task_service
    task_id = task_service.task_for_run(run_id)
    if task_id is not None:
        await task_service.cancel(task_id)
        return {"ok": True}
    if run_registry.cancel(run_id):
        return {"ok": True}
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    raise HTTPException(status_code=409, detail=f"run is not cancellable (status={run.status})")


@router.post("/runs/{run_id}/rescore")
async def rescore_run(run_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    """Manually re-enqueue judge scoring for one run (E1). 404 on unknown run.

    Auth: covered by the router-level require_auth dependency.
    E2 + Task-2 review S5: accepts kind in ('live', 'scheduled') — scheduled runs are
    judge-scored exactly like live ones (matches the reaper's _REAPED_KINDS policy);
    replay runs end in terminal status 'replayed' and are never judged, so
    re-enqueueing one is a client error, not a no-op.
    S3-M1: also rejects non-rescorable statuses with 409 — cancelled/interrupted runs
    are terminal and never scored; rescoring one would judge partial output and flip
    it to 'scored' (corpus-eligible), breaching the milestone invariant.
    """
    from server.services import run_recorder

    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.no_learning:
        raise HTTPException(status_code=409, detail={"code": "run_learning_disabled"})
    if run.kind not in ("live", "scheduled"):
        raise HTTPException(status_code=409,
                            detail="only live/scheduled runs can be rescored")
    if run.status not in ("recorded", "scored", "score_failed"):
        raise HTTPException(status_code=409,
                            detail=f"run is not rescorable (status={run.status})")
    run_recorder.schedule_scoring(run_id)
    return {"enqueued": True}


@router.post("/runs/{run_id}/redact")
async def redact_run_endpoint(run_id: int) -> dict:
    """Manually clear sensitive/bulky debug detail for one run. No-op if it doesn't exist."""
    from server.services import run_redact

    await run_redact.redact_run(run_id)
    return {"redacted": True}


@router.post("/runs/redact-all")
async def redact_all_endpoint() -> dict:
    """Manually clear sensitive/bulky debug detail for every run. Returns the count touched."""
    from server.services import run_redact

    n = await run_redact.redact_all()
    return {"redacted": n}
