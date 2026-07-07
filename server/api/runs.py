"""Read-only Run replay + evaluation endpoint."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.db.models import Run, RunEvaluation, RunStep
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


@router.get("/runs", response_model=list[RunListItemOut])
async def list_runs(
    spawn_id: int | None = None,
    conversation_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> list[RunListItemOut]:
    q = select(Run).order_by(Run.id.desc()).limit(limit)
    if spawn_id is not None:
        q = q.where(Run.spawn_id == spawn_id)
    if conversation_id is not None:
        q = q.where(Run.conversation_id == conversation_id)
    rows = (await db.execute(q)).scalars().all()
    return [
        RunListItemOut(
            id=r.id, spawn_name=r.spawn_name, status=r.status,
            overall_score=r.overall_score, overall_badge=r.overall_badge,
            total_ms=r.total_ms, user_message=r.user_message,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]


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
    q = select(Run)
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
    q = select(Run)
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
    q = select(Run)
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
                title=f"{name} 错误率偏高", detail=f"{round(err_ratio*100)}% · {len(errs)}/{n} 报错", since=since0))
        elif n >= 3 and err_ratio > ERR_AMBER:
            out.append(AnomalyOut(severity="amber", kind="error_rate", spawn_id=sid, spawn_name=name,
                title=f"{name} 错误率上升", detail=f"{round(err_ratio*100)}%", since=since0))
        for dim in DIMENSIONS:
            streak = 0
            first_ts = None
            for r in rs:
                if dim in fail_dims.get(r.id, set()):
                    streak += 1
                    first_ts = first_ts or (r.created_at.isoformat() if r.created_at else None)
                    if streak >= 2:
                        out.append(AnomalyOut(severity="red", kind="fabrication" if dim == "fabrication" else dim,
                            spawn_id=sid, spawn_name=name, title=f"{name} 连续 {dim} 校验失败",
                            detail=f"连续 ≥2 个 run {dim} fail", since=first_ts, run_id=r.id))
                        break
                else:
                    streak = 0
                    first_ts = None
        scored = [r.overall_score for r in rs if r.status == "scored" and r.overall_score is not None]
        if len(scored) >= 3:
            pr = round(sum(1 for s in scored if s >= PASS_THRESHOLD) / len(scored) * 100)
            if pr < PASS_RED:
                out.append(AnomalyOut(severity="amber", kind="pass_rate", spawn_id=sid, spawn_name=name,
                    title=f"{name} 达标率偏低", detail=f"{pr}% 达标", since=None))

    if run_ids:
        for rid, ref in (await db.execute(
            select(RunStep.run_id, RunStep.ref).where(RunStep.run_id.in_(run_ids), RunStep.kind == "tool_call")
        )).all():
            if isinstance(ref, dict) and ref.get("ok") is False:
                rn = next((r for r in runs if r.id == rid), None)
                out.append(AnomalyOut(severity="amber", kind="tool_error",
                    spawn_id=rn.spawn_id if rn else None, spawn_name=(rn.spawn_name if rn else None),
                    title=f"{rn.spawn_name if rn else '分身'} 工具报错",
                    detail=f"{ref.get('tool','tool')} 失败 · run #{rid}",
                    since=(rn.created_at.isoformat() if rn and rn.created_at else None), run_id=rid))
                break
    out.sort(key=lambda a: 0 if a.severity == "red" else 1)
    return out


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: int, db: AsyncSession = Depends(get_session)) -> RunDetailOut:
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
        run=RunOut(
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
        ),
        steps=[RunStepOut(seq=s.seq, kind=s.kind, ref=s.ref or {}, detail=s.detail or {},
                          duration_ms=s.duration_ms) for s in steps],
        evaluations=[RunEvaluationOut(dimension=e.dimension, status=e.status,
                                      score=e.score, comment=e.comment) for e in evals],
    )


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
