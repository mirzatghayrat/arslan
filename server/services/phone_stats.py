"""The week and the task results on the phone's Overview (IPB, docs/plans/0164/IPB-frame-list.md §2):
`status.snapshot.week` and `status.snapshot.outcomes`. Built from persisted rows only (runs, tasks,
the approval ledger, usage), so a restart never resets them, unlike today's `activity`, which counts
running jobs and the island's events from memory.

The Bridge reads `/api/v1/phone/status` every 2 s, so both blocks are cached for a minute, and built
again sooner when a run starts or ends, a task changes or a card is asked.
"""
from __future__ import annotations

import time
import unicodedata
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock
from pathlib import Path

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import ApprovalEvent, ArslanMessage, Judgment, Run
from server.db.task_models import CompanionTask, TaskAttempt, TaskRevision
from server.services import background_jobs, home_text, phone_reads

DAYS = 7
#: Finished tasks per set (today, week), newest first. The whole snapshot is written to iCloud on each
#: 60 s heartbeat, so the list is capped; past it, the phone's counts of the week undercount (frame
#: list, Decide 2). Pinned by a shared vector, so a later counts field can replace it cleanly.
TASK_CAP = 50
TITLE_MAX = 80
CACHE_SECONDS = 60
#: Who had a card in front of them: the person, or nobody in time (§A8). Not a rule, a grant, the
#: floor, or "away" (a card that never opened).
ASKED = ("user", "expired")
#: A finished job's outcome in the phone's words, as the conversation list maps it (phone_reads.describe),
#: plus a restart that cut it short, which the frame list counts as unfinished.
STATES = {"done": "done", "partial": "unfinished", "blocked": "unfinished", "out_of_budget": "unfinished",
          "interrupted": "unfinished", "stopped": "failed"}
NOT_FINISHED = ("queued", "running", "verifying")

_cache: dict = {}


def _reset_for_tests() -> None:
    _cache.clear()


def _home() -> Path:
    return Path.home()


#: Format characters a title keeps: the joiners inside emoji sequences and some scripts (#651 review N5).
JOINERS = {"\u200c", "\u200d"}


def clean_text(text: str | None) -> str:
    """Free text for the phone on one line, with no surrogate, control or format character but the joiners: a
    lone surrogate can't be encoded, so it failed the whole snapshot, and a bidi override reorders what the
    phone shows (#647 review F2)."""
    flat = " ".join((text or "").split())
    return " ".join("".join(ch for ch in flat if ch in JOINERS
                            or unicodedata.category(ch) not in ("Cs", "Cc", "Cf")).split())


def _title(goal: str | None) -> str:
    """The goal as the phone's one-line title (`clean_text`), with the home folder as `~` (`home_text.fold_home`,
    #651 review N1), as a conversation's folder is shown (§5.10)."""
    return phone_reads.one_line(home_text.fold_home(clean_text(goal), str(_home())), TITLE_MAX)


def _utc(local_day: date) -> datetime:
    """Local midnight of a day, as the naive UTC the rows store (DST-correct)."""
    return datetime.combine(local_day, clock()).astimezone().astimezone(UTC).replace(tzinfo=None)


def _local_day(moment: datetime) -> date:
    return moment.replace(tzinfo=UTC).astimezone().date()


async def blocks(db: AsyncSession, now: float | None = None) -> dict:
    """`{"week": [...], "outcomes": {...}}` for the snapshot, at most a minute old."""
    now = time.time() if now is None else now
    # The running jobs too: a job that just finished leaves `jobs` before its task row may change (#647 review F3).
    key = (date.fromtimestamp(now), tuple(sorted(job.job_id for job in background_jobs.active())), *(await db.execute(select(
        select(func.max(Run.id)).scalar_subquery(), select(func.max(Run.ended_at)).scalar_subquery(),
        select(func.max(CompanionTask.updated_at)).scalar_subquery(),
        select(func.max(ApprovalEvent.id)).scalar_subquery(),
        # A conversation emptied or deleted drops its tasks at once (#651 review N2).
        select(func.max(ArslanMessage.id)).scalar_subquery(), select(func.count(ArslanMessage.id)).scalar_subquery()))).one())
    hit = _cache.get("entry")
    if hit is not None and hit[0] == key and now - hit[1] < CACHE_SECONDS:
        return hit[2]
    body = await _build(db, now)
    _cache["entry"] = (key, now, body)
    return body


async def _build(db: AsyncSession, now: float) -> dict:
    today = date.fromtimestamp(now)
    first = today - timedelta(days=DAYS - 1)
    since, midnight = _utc(first), _utc(today)
    background = CompanionTask.privacy["driver"]["kind"].as_string() == "background"
    # Every run a task (a background job) took in the window: a run is linked to its task when it
    # starts, which updates the task, so a task updated before the window has no run in it.
    task_runs: set[int] = set()
    for (run_ids,) in (await db.execute(select(TaskAttempt.run_ids).join(CompanionTask, TaskAttempt.task_id == CompanionTask.id)
                                         .where(background, CompanionTask.updated_at >= since))).all():
        task_runs.update(run_ids or ())

    counts = {first + timedelta(days=k): [0, 0, 0] for k in range(DAYS)}
    for run_id, started in (await db.execute(select(Run.id, Run.started_at)
                                             .where(Run.started_at >= since, Run.kind != "replay"))).all():
        if (bucket := counts.get(_local_day(started))) is not None:
            bucket[1 if run_id in task_runs else 0] += 1
    for (created,) in (await db.execute(select(ApprovalEvent.created_at)
                                        .where(ApprovalEvent.created_at >= since, ApprovalEvent.decided_by.in_(ASKED)))).all():
        if (bucket := counts.get(_local_day(created))) is not None:
            bucket[2] += 1
    week = [{"day": d.strftime("%Y-%m-%d"), "counts": c} for d, c in counts.items()]

    running = {job.job_id for job in background_jobs.active()}
    rows = [row for row in (await db.execute(
        # A conversation that was deleted keeps its task rows but not its messages: its goals are never sent
        # again, the conversation list's rule (#647 review F1). A task whose conversation never had a message
        # is not listed either: an Inbox "Do it" job that was stopped in a thread nothing was written to
        # (#651 review N2; the spec says so). Undo (turn_undo) follows.
        select(CompanionTask).where(background, CompanionTask.updated_at >= since, CompanionTask.phase.not_in(NOT_FINISHED),
                                    exists().where(ArslanMessage.conversation_id == CompanionTask.conversation_id))
        .order_by(CompanionTask.updated_at.desc(), CompanionTask.id))).scalars() if row.id not in running][:TASK_CAP]
    tasks = await _tasks(db, rows)
    return {"week": week, "outcomes": {
        "today": await _set([t for t, row in zip(tasks, rows) if row.updated_at >= midnight], midnight),
        "week": await _set(tasks, since)}}


async def _tasks(db: AsyncSession, rows: list[CompanionTask]) -> list[dict]:
    from server.api.usage import fetch_usage_items
    ids = [row.id for row in rows]
    if not ids:
        return []
    specs = {(task_id, revision): spec for task_id, revision, spec in (await db.execute(
        select(TaskRevision.task_id, TaskRevision.revision, TaskRevision.spec).where(TaskRevision.task_id.in_(ids)))).all()}
    runs: dict[str, set[int]] = {}
    for task_id, run_ids in (await db.execute(select(TaskAttempt.task_id, TaskAttempt.run_ids)
                                              .where(TaskAttempt.task_id.in_(ids)))).all():
        runs.setdefault(task_id, set()).update(run_ids or ())
    needed = set((await db.execute(select(ApprovalEvent.job_id).where(
        ApprovalEvent.job_id.in_(ids), ApprovalEvent.decided_by.in_(ASKED)))).scalars())
    # A job with no checks of its own that answered is judged once more ("was the goal reached"); a
    # confident no turned its done into blocked (background_jobs._goal_not_reached). The newest per job.
    verdicts = {ref: (verdict, probability) for ref, verdict, probability in (await db.execute(
        select(Judgment.ref, Judgment.verdict, Judgment.probability)
        .where(Judgment.point == "job.accomplished", Judgment.ref.in_(ids)).order_by(Judgment.id))).all()}
    out = []
    for row in rows:
        spec = specs.get((row.id, row.spec_revision)) or {}
        checks = [c.get("id") for c in spec.get("acceptance") or () if c.get("id") != "answer-delivered"]
        results = {r.get("check_id"): r.get("status") for r in row.results or ()}
        if row.phase == "cancelled" and row.pause_reason == "process_interrupted":
            outcome = "interrupted"
        else:
            outcome = background_jobs.outcome_of(row.phase, results, row.pause_reason)
        if outcome == "done" and background_jobs.goal_missed(*verdicts.get(row.id, (None, None))):
            outcome = "blocked"
        item = {"conversation_id": row.conversation_id, "title": _title(spec.get("instruction")),
                "state": STATES[outcome],
                "checks_passed": sum(results.get(c) in ("passed", "not_applicable") for c in checks),
                "checks_total": len(checks), "needed_you": row.id in needed}
        spent, _ = _spent(await fetch_usage_items(run_ids=runs.get(row.id, set())))
        if spent is not None:
            item["spent_usd"] = spent
        out.append(item)
    return out


async def _set(tasks: list[dict], since: datetime) -> dict:
    from server.api.usage import fetch_usage_items
    spent, partial = _spent(await fetch_usage_items(since=since, include_replay=True))
    spent = spent or 0.0
    listed = sum(t.get("spent_usd", 0.0) for t in tasks)
    return {"tasks": tasks, "spent_usd": spent, "other_spent_usd": round(max(spent - listed, 0.0), 4),
            **({"spent_partial": True} if partial else {})}


def _spent(items: list[tuple]) -> tuple[float | None, bool]:
    """US dollars over usage items, priced as the Progress page prices them (`item_usd`): None when
    nothing could be priced, and whether any use had no price."""
    from server.api.usage import item_usd
    total, partial = None, False
    for _scope, provider, model, tokens_in, tokens_out, estimated, tokens, _ts in items:
        usd = item_usd(model, tokens_in, tokens_out, estimated, provider)
        if usd is None:
            partial = partial or tokens > 0
        else:
            total = (total or 0.0) + usd
    return (None if total is None else round(total, 4)), partial
