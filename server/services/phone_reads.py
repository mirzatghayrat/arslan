"""What the Arslan Bridge reads for a paired iPhone beyond the plain lists (mobile bridge §5.3):
a run's steps for quick review, each conversation's kind and state, today's activity, and
starting or stopping a task from the phone. Pure shaping over the database, the run recorder
and the job registry; the HTTP routes are in server/api/phone.py.
"""
from __future__ import annotations

import difflib
import time
from datetime import UTC, datetime
from pathlib import PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import ArslanMessage, Run, RunStep, ScheduledTask
from server.services import artifact_store, background_jobs, desktop_status, run_registry, turn_journal

#: A file travels to the phone inside one CloudKit record (protocol §4.6).
PHONE_FILE_MAX = 20 * 1024 * 1024
REMOTE_ID = "pocket"            # the phone's own conversation; shown everywhere as "Remote"
REMOTE_TITLE = "Remote"
STEPS_SHOWN = 40                # the newest steps of a run; `total` says how many there were
DIFF_LINES = 160                # lines of one change sent to the phone
CONTEXT = 2                     # unchanged lines kept around a change
PREVIEW = 80


def iso(moment) -> str:
    """The protocol's timestamps: UTC, whole seconds, "Z" (rows are stored as naive UTC)."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if moment is None:
        return "1970-01-01T00:00:00Z"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def one_line(text: str | None, limit: int = PREVIEW) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# ------------------------------------------------------------------ files

def file_reference(item: dict) -> dict | None:
    """One run artifact as the phone's file reference (`file.offer` body); None when it is too
    big to travel. The id is the artifact's own filename (`run_<id>_<uuid>_<name>`)."""
    size = item.get("bytes")
    if not isinstance(size, int) or size > PHONE_FILE_MAX:
        return None
    filename = item["filename"]
    return {"id": filename, "name": PurePosixPath(item.get("title") or filename).name or filename,
            "size": size, "mime_type": item.get("media_type") or "application/octet-stream",
            "sha256": item["sha256"]}


def artifact_counts() -> dict[int, int]:
    """Files per run, from one listing of the artifact folder (names start `run_<id>_`)."""
    directory = artifact_store.root()
    counts: dict[int, int] = {}
    if not directory.exists():
        return counts
    for path in directory.glob("run_*.manifest.json"):
        head = path.name.split("_", 2)
        if len(head) > 2 and head[1].isdigit():
            counts[int(head[1])] = counts.get(int(head[1]), 0) + 1
    return counts


def run_files(run_id: int | None) -> list[dict]:
    if not run_id:
        return []
    return [ref for ref in map(file_reference, artifact_store.list_artifacts(run_id)) if ref]


# ------------------------------------------------------------------ a run, for review

STEP_KINDS = {"run_command": "command", "edit_file": "edit", "write_file": "write", "web_search": "search",
              "web_extract": "web", "browser_open": "web", "read_file": "read", "list_dir": "read",
              "update_plan": "plan"}


def change_lines(old: str, new: str) -> tuple[list[list], int, int]:
    """A line diff of one edit for a phone screen: [op, old_no, new_no, text] rows with two lines
    of context, long unchanged stretches folded to ["fold", None, None, "<n>"], capped."""
    a, b = old.splitlines(), new.splitlines()
    rows: list[list] = []
    added = removed = 0
    ops = difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
    for index, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            span = i2 - i1
            head = 0 if index == 0 else CONTEXT              # after the change before it
            tail = 0 if index == len(ops) - 1 else CONTEXT   # before the change after it
            if span <= head + tail + 1:
                rows += [[" ", i1 + k + 1, j1 + k + 1, a[i1 + k]] for k in range(span)]
            else:
                rows += [[" ", i1 + k + 1, j1 + k + 1, a[i1 + k]] for k in range(head)]
                if tail:
                    rows.append(["fold", None, None, str(span - head - tail)])
                rows += [[" ", i2 - tail + k + 1, j2 - tail + k + 1, a[i2 - tail + k]] for k in range(tail)]
            continue
        rows += [["-", i1 + k + 1, None, a[i1 + k]] for k in range(i2 - i1)]
        rows += [["+", None, j1 + k + 1, b[j1 + k]] for k in range(j2 - j1)]
        removed += i2 - i1
        added += j2 - j1
    if rows and rows[-1][0] == "fold":
        rows.pop()
    if len(rows) > DIFF_LINES:
        rows = rows[:DIFF_LINES] + [["fold", None, None, "…"]]
    return rows, added, removed


def phone_step(tool: str, ok: bool, ms: int | None, detail: dict) -> dict:
    review = detail.get("review") if isinstance(detail.get("review"), dict) else {}
    kind = review.get("kind") or STEP_KINDS.get(tool, "other")
    step: dict = {"kind": kind, "tool": tool, "ok": bool(ok), "ms": ms if isinstance(ms, int) else None,
                  "target": one_line(detail.get("target") or review.get("path") or review.get("url")
                                     or review.get("query") or review.get("command") or "", 120),
                  "summary": one_line(detail.get("summary"), 160)}
    if kind == "command" and review:
        step["terminal"] = {"command": review.get("command") or "", "exit": review.get("exit"),
                            "lines": list(review.get("lines") or [])}
    elif kind == "edit" and review:
        rows, added, removed = change_lines(review.get("old") or "", review.get("new") or "")
        step["diff"] = {"path": review.get("path") or "", "added": added, "removed": removed, "lines": rows,
                        "new_file": False}
    elif kind == "write" and review:
        head = (review.get("head") or "").splitlines()
        shown = head[:40]
        step["diff"] = {"path": review.get("path") or "", "added": len(head), "removed": 0, "new_file": True,
                        "lines": [["+", None, k + 1, line] for k, line in enumerate(shown)]
                        + ([["fold", None, None, "…"]] if len(head) > len(shown) or (review.get("head") or "").endswith("…") else [])}
        if review.get("file_id"):
            step["file_id"] = review["file_id"]
    return step


def live_steps(events: list) -> list[dict]:
    """Steps of a run still in flight, from its recorder's events (tool_call/tool_result pairs)."""
    steps, pending = [], None
    for ts, event in events:
        kind = event.get("type")
        if kind == "tool_call":
            pending = (ts, event)
        elif kind == "tool_result" and pending is not None:
            call_ts, call = pending
            ms = int((ts - call_ts).total_seconds() * 1000) if ts and call_ts else None
            detail = {"target": call.get("target"), "summary": event.get("summary"), "review": event.get("review")}
            steps.append(phone_step(event.get("tool") or call.get("tool") or "", bool(event.get("ok")), ms, detail))
            pending = None
    if pending is not None:
        _, call = pending
        steps.append(phone_step(call.get("tool") or "", True, None, {"target": call.get("target")}) | {"running": True})
    return steps


def run_state(run: Run, live: bool) -> str:
    if live or run.status == "recording":
        return "working"
    if run.status == "cancelled":
        return "stopped"
    if run.error_kind or run.status == "interrupted":
        return "failed"
    return "done"


async def run_detail(db: AsyncSession, run_id: int) -> dict | None:
    run = await db.get(Run, run_id)
    if run is None:
        return None
    recorder = run_registry._recorders.get(run_id)
    live = recorder is not None and not getattr(recorder, "_finalized", False)
    if live:
        steps = live_steps(list(recorder._events))
        started = run.started_at
        duration = int((datetime.now(UTC).replace(tzinfo=None) - started).total_seconds() * 1000) if started else None
    else:
        rows = (await db.execute(select(RunStep).where(RunStep.run_id == run_id, RunStep.kind == "tool_call")
                                 .order_by(RunStep.seq))).scalars().all()
        steps = [phone_step((row.ref or {}).get("tool") or "", bool((row.ref or {}).get("ok")), row.duration_ms,
                            row.detail or {}) for row in rows]
        duration = run.total_ms
    total = len(steps)
    return {"run_id": run_id, "conversation_id": run.conversation_id, "title": one_line(run.user_message, 200),
            "state": run_state(run, live), "started_at": iso(run.started_at), "duration_ms": duration,
            "total": total, "steps": steps[-STEPS_SHOWN:], "files": run_files(run_id)}


# ------------------------------------------------------------------ conversations, with kind and state

async def describe(db: AsyncSession, ids: list[str]) -> dict[str, dict]:
    """kind / state / origin / preview / files for each conversation id."""
    if not ids:
        return {}
    last_ids = dict((await db.execute(select(ArslanMessage.conversation_id, func.max(ArslanMessage.id))
                                      .where(ArslanMessage.conversation_id.in_(ids))
                                      .group_by(ArslanMessage.conversation_id))).all())
    first_user = dict((await db.execute(select(ArslanMessage.conversation_id, func.min(ArslanMessage.id))
                                        .where(ArslanMessage.conversation_id.in_(ids), ArslanMessage.role == "user")
                                        .group_by(ArslanMessage.conversation_id))).all())
    wanted = set(last_ids.values()) | set(first_user.values())
    messages = {m.id: m for m in (await db.execute(select(ArslanMessage).where(ArslanMessage.id.in_(wanted)))).scalars()}
    outcomes = dict((await db.execute(select(ArslanMessage.conversation_id, ArslanMessage.job_outcome)
                                      .where(ArslanMessage.conversation_id.in_(ids), ArslanMessage.job_outcome.is_not(None))
                                      .order_by(ArslanMessage.id))).all())
    runs: dict[str, list[int]] = {}
    for cid, run_id in (await db.execute(select(ArslanMessage.conversation_id, ArslanMessage.run_id)
                                         .where(ArslanMessage.conversation_id.in_(ids), ArslanMessage.run_id.is_not(None)))).all():
        runs.setdefault(cid, []).append(run_id)
    scheduled = {cid for (cid,) in (await db.execute(select(ScheduledTask.conversation_id)
                                                     .where(ScheduledTask.conversation_id.is_not(None)))).all()}
    waiting = set(desktop_status.island_feed()["awaiting_conversations"])
    per_run = artifact_counts()
    out = {}
    for cid in ids:
        jobs = background_jobs.jobs_for(cid)
        running_job = next((j for j in jobs if j.phase != "finished"), None)
        latest_job = max(jobs, key=lambda j: j.started_at) if jobs else None
        if cid == REMOTE_ID:
            kind = "remote"
        elif jobs or cid in outcomes or cid.startswith("task-"):
            kind = "task"
        elif cid.startswith("scheduled-") or (cid in scheduled and cid not in first_user):
            kind = "scheduled"
        else:
            kind = "chat"
        if cid in waiting:
            state = "waiting"
        elif running_job or run_registry.active_for(cid) or turn_journal.active(cid):
            state = "working"
        else:
            outcome = (latest_job.outcome if latest_job and latest_job.phase == "finished" else None) or outcomes.get(cid)
            # Done only when it got done; not getting there (partly, stuck, out of budget, or saying
            # so itself) reads "unfinished" (the phone's yellow 没做成), a stop reads "failed".
            state = {"done": "done", "partial": "unfinished", "blocked": "unfinished", "out_of_budget": "unfinished",
                     "stopped": "failed"}.get(outcome or "", "idle")
        first = messages.get(first_user.get(cid))
        last = messages.get(last_ids.get(cid))
        files = sum(per_run.get(run_id, 0) for run_id in set(runs.get(cid, [])))
        item = {"kind": kind, "state": state, "origin": "phone" if (first is not None and first.source == "phone") else "mac",
                "preview": one_line(last.display_content or last.content) if last is not None else "", "files": files}
        if running_job is not None:
            # The job's own checks, as its job.event counts them ("answer-delivered" is every job's).
            checks = [c["id"] for c in running_job.acceptance if c["id"] != "answer-delivered"]
            item["job"] = {"id": running_job.job_id, "step": running_job.step or "",
                           "done": sum(1 for check in checks if running_job.results.get(check) == "passed"),
                           "total": len(checks)}
        out[cid] = item
    return out


# ------------------------------------------------------------------ today's activity

def _local_hour(moment: datetime) -> int:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone().hour


async def activity(db: AsyncSession, now: float | None = None) -> dict:
    """Today on this Mac, for the phone's chart: per local hour [chat turns, tasks, approvals],
    plus finished runs, files made and cards waiting."""
    now = time.time() if now is None else now
    local = datetime.fromtimestamp(now).astimezone()
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    since = midnight.astimezone(UTC).replace(tzinfo=None)
    rows = (await db.execute(select(Run.id, Run.started_at, Run.status, Run.error_kind)
                             .where(Run.started_at >= since, Run.kind != "replay"))).all()
    job_runs = {job.run_id for job in background_jobs._jobs.values() if job.run_id}
    hours = [[0, 0, 0] for _ in range(24)]
    done = 0
    for run_id, started, status, error in rows:
        hours[_local_hour(started)][1 if run_id in job_runs else 0] += 1
        done += status in ("recorded", "scored", "replayed") and not error
    for event in desktop_status.snapshot()["events"]:
        if event["kind"] == "approval_needed" and event["at"] >= midnight.timestamp():
            hours[datetime.fromtimestamp(event["at"]).hour][2] += 1
    files = 0
    directory = artifact_store.root()
    if directory.exists():
        files = sum(1 for path in directory.glob("run_*.manifest.json") if path.stat().st_mtime >= midnight.timestamp())
    return {"hours": hours, "done": done, "files": files, "waiting": desktop_status.snapshot()["awaiting"]}


# ------------------------------------------------------------------ tasks from the phone

TASK_PREFIX = "task-"
MAX_CRITERIA = 3


async def start_task(goal: str, criteria: list[str]) -> dict:
    """A task the phone hands over: its own conversation (so it has a title, a history and a
    place in both sidebars), the goal as the phone's message, and a background job."""
    import uuid
    from server.orchestrator import memory
    goal = " ".join((goal or "").split())
    if not goal:
        raise ValueError("task_goal_required")
    conversation_id = TASK_PREFIX + uuid.uuid4().hex[:12]
    await memory.add_message(conversation_id, "user", goal, source="phone")
    wanted = [{"description": " ".join(str(c).split())[:300]} for c in criteria if str(c).strip()][:MAX_CRITERIA]
    job = await background_jobs.start(conversation_id, goal, wanted, origin="phone")
    return {"conversation_id": conversation_id, "job_id": job.job_id}


def stop_task(job_id: str) -> bool:
    job = background_jobs._jobs.get(job_id)
    return job is not None and background_jobs.stop(job.conversation_id, job_id)
