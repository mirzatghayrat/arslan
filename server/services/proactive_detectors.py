"""Proactivity detectors (0.1.47): deterministic, free, read-only.

Each detector looks at something Arslan already has — finished background jobs,
scheduled tasks, pages and folders the user asked it to watch — and returns
candidates WITH evidence. None of them calls a model, and none acts: what to do
about a finding is the user's decision, made in the inbox.

Watch detectors move their stored baseline only through `Found.ack`, which the
service calls after the candidate has been handled. If saving the item fails the
baseline has not moved, so the change is seen again next time instead of lost.

Text that came from outside (page lines, file names) is only ever carried as an
evidence `quote`, which the UI shows in quotation marks and nothing obeys.
"""
from __future__ import annotations

import difflib
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from arslan.proactive_policy import JOB_REASONS, Candidate, Evidence, ProactiveConfig, cooldown_over
from server.db import session as db_session
from server.db.models import (CompanionTask, ProactiveWatch, ScheduledTask, ScheduledTaskRun, TaskRevision)
from server.services import background_jobs, runtime_messages

#: Tasks stop being interesting after this long (the policy also expires items).
LOOKBACK = timedelta(days=7)
#: A job that just ended has already told the user; wait before raising a follow-up.
SETTLE = timedelta(minutes=10)
STOPPED_REASONS = set(JOB_REASONS) - {"other"}
MAX_QUOTES = 4
MAX_QUOTE_CHARS = 200
MAX_PAGE_CHARS = 40_000
MAX_FOLDER_ENTRIES = 5000
HEARTBEAT_NAME = "__heartbeat__"


@dataclass
class Found:
    candidate: Candidate
    ack: Callable[[], Awaitable[None]] | None = None


@dataclass
class Context:
    now: datetime                       # naive UTC, like every stored timestamp
    config: ProactiveConfig
    locale: str = "en"
    workspace: Path | None = None
    fetch: Callable[[str], Awaitable[str]] | None = None


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def _say(ctx: Context, key: str, **values) -> str:
    return runtime_messages.render(key, ctx.locale, **values)


# ── finished background jobs that did not finish the job ─────────────────────

async def job_followups(ctx: Context) -> list[Found]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(CompanionTask).where(
            CompanionTask.phase.in_(("waiting_user", "failed")),
            CompanionTask.updated_at >= ctx.now - LOOKBACK,
            CompanionTask.updated_at <= ctx.now - SETTLE))).scalars().all()
        found = []
        for row in rows:
            if ((row.privacy or {}).get("driver") or {}).get("kind") != "background":
                continue
            revision = await db.get(TaskRevision, (row.id, row.spec_revision))
            spec = (revision.spec if revision else None) or {}
            goal = " ".join(str(spec.get("instruction") or "").split())
            if not goal:
                continue
            reason = row.pause_reason if row.pause_reason in STOPPED_REASONS else (
                "execution_failed" if row.phase == "failed" else "other")
            found.append(Found(Candidate(
                kind="job_followup", fingerprint=f"job:{row.id}", source_key=f"job:{row.id}",
                title_key="title.job_followup", params={"goal": goal[:140]},
                evidence=(Evidence("job.goal", {}, quote=goal[:MAX_QUOTE_CHARS]),
                          Evidence(f"job.reason.{reason}", {"at": row.updated_at.isoformat()})),
                goal=_say(ctx, "proactive_goal_followup", goal=goal[:600]),
                criteria=tuple(background_jobs.criteria_from_acceptance(spec.get("acceptance") or [])),
                priority="high" if reason in {"task_budget_exhausted", "task_input_required"} else "normal",
                conversation_id=row.conversation_id)))
        return found


# ── scheduled tasks that keep failing ────────────────────────────────────────

async def scheduled_problems(ctx: Context) -> list[Found]:
    async with db_session.AsyncSessionLocal() as db:
        tasks = (await db.execute(select(ScheduledTask).where(ScheduledTask.name != HEARTBEAT_NAME))).scalars().all()
        found = []
        for task in tasks:
            paused = bool(task.paused_reason)
            failing = task.enabled and (task.consecutive_failures or 0) >= 2
            if not (paused or failing):
                continue
            runs = (await db.execute(select(ScheduledTaskRun).where(
                ScheduledTaskRun.task_id == task.id, ScheduledTaskRun.outcome == "error")
                .order_by(ScheduledTaskRun.id.desc()).limit(3))).scalars().all()
            evidence = [Evidence("sched.state", {"name": task.name, "failures": task.consecutive_failures or 0,
                                                 "paused": paused})]
            for run in runs:
                evidence.append(Evidence("sched.run", {"at": (run.started_at or ctx.now).isoformat()},
                                         quote=" ".join(str(run.reason or "").split())[:MAX_QUOTE_CHARS] or None))
            found.append(Found(Candidate(
                kind="scheduled_problem",
                fingerprint=f"sched:{task.id}:{'p' if paused else 'f'}{task.consecutive_failures or 0}:"
                            f"{_digest(task.paused_reason or '')[:6]}",
                source_key=f"sched:{task.id}", title_key="title.scheduled_problem", params={"name": task.name},
                evidence=tuple(evidence),
                goal=_say(ctx, "proactive_goal_scheduled", name=task.name, prompt=(task.prompt or "")[:500]),
                criteria=({"description": _say(ctx, "proactive_crit_report"), "kind": "judgement"},),
                priority="high" if paused else "normal")))
        return found


# ── web pages the user asked to watch ────────────────────────────────────────

def _normalize(text: str) -> list[str]:
    return [line for line in (" ".join(raw.split()) for raw in text.splitlines()) if line]


def changed_lines(old: str, new: str) -> tuple[list[str], list[str]]:
    """(added, removed) lines between two page texts."""
    a, b = _normalize(old), _normalize(new)
    added, removed = [], []
    for line in difflib.unified_diff(a, b, lineterm="", n=0):
        if line.startswith(("+++", "---", "@@")):
            continue
        (added if line.startswith("+") else removed).append(line[1:])
    return added, removed


def significant(old: str, new: str) -> bool:
    """Real change, not a ticking timestamp: at least two changed lines AND at
    least 1% of the page. A one-line price edit on a short page passes; a clock on
    a long page does not."""
    added, removed = changed_lines(old, new)
    total = max(len(_normalize(old)), len(_normalize(new)), 1)
    changed = len(added) + len(removed)
    return changed >= 2 and changed / (2 * total) >= 0.01


async def default_fetch(url: str) -> str:
    from server.registry.executors import WebExtractExecutor
    result = await WebExtractExecutor().execute({"url": url, "max_chars": MAX_PAGE_CHARS})
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "fetch failed")[:150])
    return str(result["text"])


async def _save_watch(watch_id: int, **fields) -> None:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(ProactiveWatch, watch_id)
        if row is not None:
            for key, value in fields.items():
                setattr(row, key, value)
            await db.commit()


def _due(watch: ProactiveWatch, now: datetime) -> bool:
    return watch.enabled and (watch.last_checked_at is None
                              or now - watch.last_checked_at >= timedelta(seconds=watch.interval_s))


async def web_changes(ctx: Context) -> list[Found]:
    fetch = ctx.fetch or default_fetch
    async with db_session.AsyncSessionLocal() as db:
        watches = (await db.execute(select(ProactiveWatch).where(
            ProactiveWatch.kind == "web", ProactiveWatch.enabled.is_(True)))).scalars().all()
    found = []
    for watch in watches:
        if not _due(watch, ctx.now):
            continue
        try:
            text = await fetch(watch.target)
        except Exception as exc:  # noqa: BLE001 — a dead page is a status, never an item
            await _save_watch(watch.id, last_checked_at=ctx.now, last_error=str(exc)[:200],
                              consecutive_errors=(watch.consecutive_errors or 0) + 1)
            continue
        seen, baseline = _digest(text), (watch.snapshot or {}).get("text")
        base = dict(last_checked_at=ctx.now, last_error=None, consecutive_errors=0, last_hash=seen)
        if baseline is None:                       # first look: remember it, raise nothing
            await _save_watch(watch.id, snapshot={"text": text}, **base)
            continue
        # No "same as last fetch, skip" shortcut: a change held back by the cooldown
        # looks identical to the last fetch, and must still be reported once the
        # day is up. Comparing to the baseline each time costs nothing.
        if not significant(baseline, text) or not cooldown_over(watch.last_item_at, ctx.now):
            await _save_watch(watch.id, **base)    # baseline stays: slow drift still adds up
            continue
        added, removed = changed_lines(baseline, text)

        async def ack(watch_id=watch.id, text=text, base=base):
            await _save_watch(watch_id, snapshot={"text": text}, last_changed_at=ctx.now,
                              last_item_at=ctx.now, **base)
        quotes = [Evidence("web.added", quote=line[:MAX_QUOTE_CHARS]) for line in added[:MAX_QUOTES]] + \
                 [Evidence("web.removed", quote=line[:MAX_QUOTE_CHARS]) for line in removed[:MAX_QUOTES]]
        found.append(Found(Candidate(
            kind="web_change", fingerprint=f"web:{watch.id}:{seen}", source_key=f"watch:{watch.id}",
            title_key="title.web_change", params={"label": watch.label},
            evidence=(Evidence("web.changed", {"label": watch.label, "url": watch.target,
                                               "added": len(added), "removed": len(removed)}), *quotes),
            goal=_say(ctx, "proactive_goal_web", url=watch.target),
            criteria=({"description": _say(ctx, "proactive_crit_report"), "kind": "judgement"},),
            notify=bool(watch.notify)), ack))
    return found


# ── folders (inside the workspace) the user asked to watch ──────────────────

def inside(workspace: Path | None, target: str) -> Path | None:
    """The real path if `target` is a directory inside the workspace, else None."""
    if workspace is None:
        return None
    try:
        path = Path(target).expanduser().resolve()
        return path if path.is_dir() and path.is_relative_to(workspace.resolve()) else None
    except (OSError, RuntimeError):
        return None


def list_names(path: Path) -> list[str]:
    names = []
    for entry in path.iterdir():
        if not entry.name.startswith("."):
            names.append(entry.name)
        if len(names) >= MAX_FOLDER_ENTRIES:
            break
    return sorted(names)


async def folder_changes(ctx: Context) -> list[Found]:
    async with db_session.AsyncSessionLocal() as db:
        watches = (await db.execute(select(ProactiveWatch).where(
            ProactiveWatch.kind == "folder", ProactiveWatch.enabled.is_(True)))).scalars().all()
    found = []
    for watch in watches:
        if not _due(watch, ctx.now):
            continue
        path = inside(ctx.workspace, watch.target)
        if path is None:
            await _save_watch(watch.id, last_checked_at=ctx.now, last_error="outside_workspace",
                              consecutive_errors=(watch.consecutive_errors or 0) + 1)
            continue
        try:
            names = list_names(path)
        except OSError as exc:
            await _save_watch(watch.id, last_checked_at=ctx.now, last_error=type(exc).__name__,
                              consecutive_errors=(watch.consecutive_errors or 0) + 1)
            continue
        base = dict(last_checked_at=ctx.now, last_error=None, consecutive_errors=0)
        previous = (watch.snapshot or {}).get("names")
        if previous is None:
            await _save_watch(watch.id, snapshot={"names": names}, **base)
            continue
        new = [n for n in names if n not in set(previous)]
        if not new or not cooldown_over(watch.last_item_at, ctx.now):
            await _save_watch(watch.id, **base, **({} if new else {"snapshot": {"names": names}}))
            continue

        async def ack(watch_id=watch.id, names=names, base=base):
            await _save_watch(watch_id, snapshot={"names": names}, last_changed_at=ctx.now,
                              last_item_at=ctx.now, **base)
        found.append(Found(Candidate(
            kind="folder_change", fingerprint=f"folder:{watch.id}:{_digest(*new)}", source_key=f"watch:{watch.id}",
            title_key="title.folder_change", params={"label": watch.label, "count": len(new)},
            evidence=(Evidence("folder.new", {"label": watch.label, "count": len(new)}),
                      *(Evidence("folder.file", quote=name[:MAX_QUOTE_CHARS]) for name in new[:8])),
            goal=_say(ctx, "proactive_goal_folder", path=str(path), count=len(new)),
            criteria=({"description": _say(ctx, "proactive_crit_report"), "kind": "judgement"},),
            notify=bool(watch.notify)), ack))
    return found


DETECTORS = {"job_followups": job_followups, "scheduled_problems": scheduled_problems,
             "web_changes": web_changes, "folder_changes": folder_changes}
