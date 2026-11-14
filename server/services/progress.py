"""INB5 (v0.1.64): what is waiting on you, counted once.

The INB card's one function: the badge reads it now, and INB7's brief ("要你做"), INB8's push and the phone are to read it too,
never a count of their own. A unit is a conversation, a project or a scheduled task, never a row:
- a conversation waits when it has a card to approve, something it could not ask while you were away that is newer than your last
  look at it (Q8, approved with the INB5 board on 2026-10-31: opening it is "handled"; the entry stays listed until it expires),
  a job's 👀 open and newer than your last look (INB9-a), or an open "the job stopped" reminder. Only conversations that still exist count (a deleted one keeps its ledger rows and
  reminders; #590 review F2), except a pending card, which is live by definition;
- a conversation in an active project counts as its project. One in an archived project counts by itself: that project has no
  row in the sidebar, where its conversations are listed under 「最近」 (#590 review F3c). INB5b makes the sidebar show every project
  that has something waiting, so a counted project always has a row even below its top few;
- a scheduled task waits when its last run failed or it paused itself, it has an open problem reminder, or one of its runs could not
  ask something newer than your last look at the task (`scheduled_tasks.seen_at`, migration 0084, set when you open the task).
  The task's own conversation counts as the task: one thing, counted once (#590 review F4). That is the one stored on its
  row (`scheduler.own_conversation`, `scheduled-<uuid>`), or `scheduled-<id>` on a row made before v0.1.64.

The window's conversation list reads `waiting_conversations` too (phone_reads.describe marks those rows "waiting"), so every
conversation the badge counts has a marked row (#590 review F3a). INB5b moves the Scheduled page's dot onto `waiting.scheduled`,
so the dot and the badge follow one rule (#590 review F3b).

INB7-f adds the brief's other three lines, counted in the same units and grouped by the same rule (`_group`): what got done
today, what is running and what is stuck (`done_today`, `running_now`, `stuck`), and `brief`, which puts the four together with
template sentences. The model's `progress_report` tool returns `brief`; Progress shows only 「要你做」 so far (the badge's count),
and when it shows the four lines it reads `brief` too, so the page and the tool can't count apart. A unit may be in more than
one line (a paused task is stuck and waits on you, as the card defines both); each line counts it once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.companion_models import ConversationContext, Project
from server.db.models import (ApprovalEvent, ArslanMessage, CompanionTask, ConversationSeen, ProactiveItem, Run, ScheduledTask,
                              ScheduledTaskRun)
from server.run_kinds import USER_RUN_KINDS
from server.services import approvals

#: How long a card nobody could answer stays listed: the window "not done while you were away" has always used.
AWAY_HOURS = 24
#: A scheduled run's entries stay a week, so a weekly task's last until its next run (the Scheduled page asks the same, INB3).
SCHEDULED_HOURS = 168
#: Reminders that are open: new or seen. One set aside ("snoozed") waits again only when it comes back.
OPEN = ("new", "seen")


@dataclass
class Waiting:
    conversations: set[str] = field(default_factory=set)
    projects: set[str] = field(default_factory=set)
    scheduled: set[int] = field(default_factory=set)
    #: INB7-f: why each unit is stuck, by (kind, id); the stuck line only. Not in `as_dict`, so the badge's answer is as it was.
    why: dict[tuple[str, object], str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.conversations) + len(self.projects) + len(self.scheduled)

    def as_dict(self) -> dict:
        return {"count": self.count, "conversations": sorted(self.conversations), "projects": sorted(self.projects),
                "scheduled": sorted(self.scheduled)}


async def _latest_not_asked(db: AsyncSession, decided_by: str, hours: int) -> dict[str, datetime]:
    """Per conversation, the newest entry of one kind of "could not ask": `away` (a card that never opened, or one nobody
    answered in time) or `policy` (a scheduled run). Kept apart: a scheduled run's entry belongs to its task, not to the
    conversation it writes into."""
    who, decision = {"away": (("away", "expired"), "expired"), "policy": (("policy",), "deny")}[decided_by]
    rows = await db.execute(select(ApprovalEvent.conversation_id, func.max(ApprovalEvent.created_at))
                            .where(ApprovalEvent.decided_by.in_(who), ApprovalEvent.decision == decision,
                                   ApprovalEvent.conversation_id.is_not(None),
                                   ApprovalEvent.created_at >= datetime.utcnow() - timedelta(hours=hours))
                            .group_by(ApprovalEvent.conversation_id))
    return dict(rows.all())


async def waiting_reasons(db: AsyncSession) -> dict[str, str]:
    """The conversations waiting on you, before projects and tasks group them, and what each waits on (INB5b-3, #590's re-check):
    "card" when a card is open, "away" when one went unanswered while you were away (nothing is left to approve, only the "not done
    while you were away" list; ⓪Plan's review of PR 614, N2), "glance" when a job's acceptance sheet left a 👀 newer than your last
    look at it (INB9-a), "reminder" when a job that stopped left one. A card wins, then an away entry: a card is a decision, the
    reminder an offer."""
    pending = {card["conversation_id"] for card in approvals.all_pending() if card.get("conversation_id")}
    away = await _latest_not_asked(db, "away", AWAY_HOURS)
    glances = await _latest_glance(db)
    looked = list(away.keys() | glances.keys())
    seen = dict((await db.execute(select(ConversationSeen.conversation_id, ConversationSeen.seen_at)
                                  .where(ConversationSeen.conversation_id.in_(looked)))).all()) if looked else {}
    unanswered = {cid for cid, latest in away.items() if cid not in seen or latest > seen[cid]}
    to_look_at = {cid for cid, latest in glances.items() if cid not in seen or latest > seen[cid]}
    reminders = set((await db.execute(select(ProactiveItem.conversation_id).where(
        ProactiveItem.kind == "job_followup", ProactiveItem.status.in_(OPEN),
        ProactiveItem.conversation_id.is_not(None)))).scalars())
    candidates = unanswered | to_look_at | reminders
    existing = set((await db.execute(select(ArslanMessage.conversation_id).distinct()
                                     .where(ArslanMessage.conversation_id.in_(list(candidates))))).scalars()) if candidates else set()
    reasons = dict.fromkeys(pending, "card")
    for cid in existing:
        reasons.setdefault(cid, "away" if cid in unanswered else "glance" if cid in to_look_at else "reminder")
    # SUB5b: a sub-session has no row of its own; it is listed under the top of its chain, which waits for it, once.
    from server.services import sub_sessions
    tops = await sub_sessions.commanders(db, reasons)
    merged: dict[str, str] = {}
    for cid, why in sorted(reasons.items(), key=lambda item: _FIRST.index(item[1])):
        merged.setdefault(tops.get(cid, cid), why)
    return merged


#: Which reason a conversation waiting on more than one shows: a card, then an away entry, then a 👀, then a reminder.
_FIRST = ("card", "away", "glance", "reminder")


async def _latest_glance(db: AsyncSession) -> dict[str, datetime]:
    """INB9-a: per conversation, the newest task within AWAY_HOURS that waits for the user's review with a 👀 open (a
    human check not passed, from a job's `glance` criteria). Accepting the review passes it (`accept_review`). Only a row
    paused for that review counts: a row paused for anything else (a check not run, one that failed) is one
    `accept_review` refuses, so its 👀 could never be closed (#900 review). Its sheet still lists what to look at."""
    rows = await db.execute(select(CompanionTask.conversation_id, CompanionTask.updated_at, CompanionTask.results)
                            .where(CompanionTask.phase == "waiting_user",
                                   CompanionTask.pause_reason == "acceptance_review_required",
                                   CompanionTask.updated_at >= datetime.utcnow() - timedelta(hours=AWAY_HOURS)))
    latest: dict[str, datetime] = {}
    for cid, updated, results in rows.all():
        if any(isinstance(item, dict) and item.get("evaluator") == "human" and item.get("status") != "passed"
               for item in results or ()):
            latest[cid] = max(updated, latest.get(cid, updated))
    return latest


async def waiting_conversations(db: AsyncSession) -> set[str]:
    """The conversations waiting on you, before projects and tasks group them."""
    return set(await waiting_reasons(db))


async def _group(db: AsyncSession, cids: set[str], tasks: list[ScheduledTask],
                 reasons: dict[str, str] | None = None) -> Waiting:
    """Conversations as units, as the badge counts them: a task's own conversation is its task, one in an active project is its
    project, any other one itself. With `reasons` (INB7-f's stuck line), each unit keeps the first of its conversations'
    reasons in `_STUCK_FIRST` order."""
    from server.services import scheduler
    out = Waiting()
    # SUB5a: a task's own conversation, also one stored on its row (scheduler.own_conversation).
    own = {task.conversation_id or f"scheduled-{task.id}": task.id for task in tasks
           if scheduler.is_own_conversation(task)}
    rest = {cid for cid in cids if cid not in own}
    project_of = dict((await db.execute(select(ConversationContext.id, ConversationContext.project_id)
                                        .join(Project, Project.id == ConversationContext.project_id)
                                        .where(ConversationContext.id.in_(rest), Project.status != "archived"))).all())
    for cid in cids:
        if cid in own:
            unit = ("scheduled_task", own[cid])
            out.scheduled.add(own[cid])
        elif cid in project_of:
            unit = ("project", project_of[cid])
            out.projects.add(project_of[cid])
        else:
            unit = ("conversation", cid)
            out.conversations.add(cid)
        if reasons and cid in reasons:
            _keep_first(out.why, unit, reasons[cid])
    return out


async def waiting_on_user(db: AsyncSession, *, hide_private: bool = False) -> Waiting:
    """`hide_private` (INB7-f, #862 review): leave out the conversations another conversation's model may not be shown
    (`private`). The badge, the user's own view, counts them all."""
    asking = await waiting_conversations(db)
    if hide_private:
        asking -= await private(db, asking)
    tasks = list((await db.execute(select(ScheduledTask))).scalars())
    out = await _group(db, asking, tasks)

    latest_run = select(ScheduledTaskRun.task_id, func.max(ScheduledTaskRun.id).label("id")).group_by(ScheduledTaskRun.task_id).subquery()
    last_outcome = dict((await db.execute(select(ScheduledTaskRun.task_id, ScheduledTaskRun.outcome)
                                          .join(latest_run, latest_run.c.id == ScheduledTaskRun.id))).all())
    problems = {key.removeprefix("sched:") for key in (await db.execute(select(ProactiveItem.source_key).where(
        ProactiveItem.kind == "scheduled_problem", ProactiveItem.status.in_(OPEN)))).scalars()}
    unasked = await _latest_not_asked(db, "policy", SCHEDULED_HOURS)
    for task in tasks:
        latest = unasked.get(task.conversation_id or f"scheduled-{task.id}")
        if (task.paused_reason is not None or last_outcome.get(task.id) == "error" or str(task.id) in problems
                or (latest is not None and (task.seen_at is None or latest > task.seen_at))):
            out.scheduled.add(task.id)
    return out


# ---------------------------------------------------------------------------------------------- INB7-f: the brief's other lines

#: A companion task at work: queued, running or checking its result. Persisted rows, never background_jobs._jobs in memory.
ACTIVE_PHASES = ("queued", "running", "verifying")
#: A run that ended and got there (usage._DONE): a reply, scored or not.
DONE_RUNS = ("completed", "recorded", "scored")
#: Why a job waits on the user's own answer: its question, its result to accept, a restored backup to look at, a changed goal.
#: Those are not stuck; every other reason a job waits for is (the card: `waiting_user`, but not waiting on the user's answer).
ANSWER_REASONS = frozenset({"task_input_required", "acceptance_review_required", "backup_restore_review_required", "goal_changed"})
#: How long something that stopped short stays stuck when nothing newer happened in its conversation: a week, as a scheduled
#: run's entries stay (SCHEDULED_HOURS).
STUCK_HOURS = SCHEDULED_HOURS
#: Which reason a unit stuck for more than one shows: a restart's cut, then a failure, a job that stopped short, your own stop,
#: and a scheduled task that paused itself.
_STUCK_FIRST = ("interrupted", "failed", "blocked", "stopped", "paused")
#: How many items each line lists; the rest are counted in `more`.
LIST_CAP = 10
#: How much of a conversation's opening line is its title: the sidebar's rule (api/conversations.py, _TITLE_CHARS).
TITLE_CHARS = 60


def _keep_first(why: dict, unit: tuple, reason: str) -> None:
    if unit not in why or _STUCK_FIRST.index(reason) < _STUCK_FIRST.index(why[unit]):
        why[unit] = reason


def today_start(now: datetime | None = None) -> datetime:
    """Today's local midnight as naive UTC, as times are stored (phone_reads.activity's "today")."""
    from datetime import timezone
    local = (now or datetime.now()).astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)


async def _tops(db: AsyncSession, cids: set[str]) -> set[str]:
    """SUB5b: a sub-session's work counts as the top of its chain's, as on the badge."""
    from server.services import sub_sessions
    tops = await sub_sessions.commanders(db, cids)
    return {tops.get(cid, cid) for cid in cids}


async def _existing(db: AsyncSession, cids: set[str]) -> set[str]:
    """Only conversations that still exist (a deleted one keeps its runs; #590 review F2)."""
    if not cids:
        return set()
    return set((await db.execute(select(ArslanMessage.conversation_id).distinct()
                                 .where(ArslanMessage.conversation_id.in_(list(cids))))).scalars())


def _background(row: CompanionTask) -> bool:
    return ((row.privacy or {}).get("driver") or {}).get("kind") == "background"


async def _tasks(db: AsyncSession) -> list[ScheduledTask]:
    return list((await db.execute(select(ScheduledTask))).scalars())


async def private(db: AsyncSession, cids: set[str]) -> set[str]:
    """Which of these conversations another conversation's model may not be shown (#862 review): those conversation_search
    never reads (`conversation_search.hidden`: temporary, "don't use memory") and quick questions, which no list shows
    (`phone_ids.kind_of`, the sidebar's rule). Left out of the counts too: a count without a title still tells."""
    from server.services import conversation_search, phone_ids
    if not cids:
        return set()
    kinds = dict((await db.execute(select(ConversationContext.id, ConversationContext.kind)
                                   .where(ConversationContext.id.in_(list(cids))))).all())
    return await conversation_search.hidden(db, cids) | {cid for cid in cids if phone_ids.kind_of(cid, kinds.get(cid)) == "quick"}


async def _shown(db: AsyncSession, cids: set[str], hide_private: bool) -> set[str]:
    return cids - await private(db, cids) if hide_private else cids


async def done_today(db: AsyncSession, now: datetime | None = None, *, hide_private: bool = False) -> Waiting:
    """「做完」: what got done since local midnight. A conversation with a reply that came without an error or a job that succeeded; a
    scheduled task with a run that went well."""
    since = today_start(now)
    replied = set((await db.execute(select(Run.conversation_id).distinct().where(
        Run.kind.in_(USER_RUN_KINDS), Run.status.in_(DONE_RUNS), Run.error_kind.is_(None), Run.ended_at >= since))).scalars())
    succeeded = set((await db.execute(select(CompanionTask.conversation_id).distinct().where(
        CompanionTask.phase == "succeeded", CompanionTask.updated_at >= since))).scalars())
    cids = await _shown(db, await _existing(db, await _tops(db, replied | succeeded)), hide_private)
    out = await _group(db, cids, await _tasks(db))
    out.scheduled |= set((await db.execute(select(ScheduledTaskRun.task_id).distinct().where(
        ScheduledTaskRun.outcome == "ok", func.coalesce(ScheduledTaskRun.finished_at, ScheduledTaskRun.started_at) >= since)))
        .scalars())
    return out


async def running_now(db: AsyncSession, *, hide_private: bool = False) -> Waiting:
    """「在做」: a companion task queued, running or checking its result, and a turn still running (its run is `recording`; a restart
    marks every such run interrupted at boot, run_reaper.mark_interrupted_runs)."""
    jobs = set((await db.execute(select(CompanionTask.conversation_id).distinct()
                                 .where(CompanionTask.phase.in_(ACTIVE_PHASES)))).scalars())
    turns = set((await db.execute(select(Run.conversation_id).distinct()
                                  .where(Run.kind.in_(USER_RUN_KINDS), Run.status == "recording"))).scalars())
    return await _group(db, await _shown(db, await _tops(db, jobs | turns), hide_private), await _tasks(db))


def _job_stuck(row: CompanionTask) -> str | None:
    """A background job's latest record, read as the card's stuck reasons. The restart's own reason is written when it happens
    (INB7-1: `cancel(reason="process_interrupted")`, and `recover_interrupted` before the boot pass reports it)."""
    if row.phase == "failed":
        return "failed"
    if row.phase == "cancelled":
        return "interrupted" if row.pause_reason == "process_interrupted" else "stopped"
    if row.phase == "waiting_user":
        if row.pause_reason == "process_interrupted":
            return "interrupted"
        return None if row.pause_reason in ANSWER_REASONS else "blocked"
    return None


def _turn_stuck(run: Run) -> str | None:
    """A conversation's latest turn: cut by a restart (the boot sweep's `interrupted`), failed, or stopped."""
    if run.status == "interrupted":
        return "interrupted"
    if run.status == "failed" or run.error_kind:
        return "failed"
    return "stopped" if run.status == "cancelled" else None


async def stuck(db: AsyncSession, now: datetime | None = None, *, hide_private: bool = False) -> Waiting:
    """「卡住」: a conversation whose latest background job or latest turn of the last week stopped short (failed, stopped, cut by a
    restart, or waiting for something other than your answer), and a scheduled task that paused itself. Something newer of the same
    kind in that conversation (a job that got done, a turn that answered) clears it. Each unit's reason is in `why`."""
    since = (now or datetime.utcnow()) - timedelta(hours=STUCK_HOURS)
    reasons: dict[str, str] = {}
    latest_job: dict[str, CompanionTask] = {}
    for row in (await db.execute(select(CompanionTask).where(or_(
            CompanionTask.updated_at >= since, CompanionTask.phase.in_(ACTIVE_PHASES))))).scalars():
        if _background(row) and (row.conversation_id not in latest_job
                                 or row.updated_at > latest_job[row.conversation_id].updated_at):
            latest_job[row.conversation_id] = row
    latest_turn: dict[str, Run] = {}
    for run in (await db.execute(select(Run).where(Run.kind.in_(USER_RUN_KINDS), or_(
            Run.created_at >= since, Run.status == "recording")).order_by(Run.id))).scalars():
        latest_turn[run.conversation_id] = run
    for cid, why in [*((cid, _job_stuck(row)) for cid, row in latest_job.items()),
                     *((cid, _turn_stuck(run)) for cid, run in latest_turn.items())]:
        if why is not None and (cid not in reasons or _STUCK_FIRST.index(why) < _STUCK_FIRST.index(reasons[cid])):
            reasons[cid] = why
    existing = await _existing(db, set(reasons))
    from server.services import sub_sessions
    tops = await sub_sessions.commanders(db, existing)
    merged: dict[str, str] = {}
    for cid in existing:
        top = tops.get(cid, cid)
        if top not in merged or _STUCK_FIRST.index(reasons[cid]) < _STUCK_FIRST.index(merged[top]):
            merged[top] = reasons[cid]
    tasks = await _tasks(db)
    out = await _group(db, await _shown(db, set(merged), hide_private), tasks, merged)
    for task in tasks:
        if task.paused_reason is not None:            # paused itself after failing; one switched off by hand isn't stuck
            out.scheduled.add(task.id)
            _keep_first(out.why, ("scheduled_task", task.id), "paused")
    return out


async def _titles(db: AsyncSession, units: list[Waiting]) -> dict[tuple[str, object], str]:
    """What the user sees each unit called: a conversation's opening line as the sidebar shows it, a project's or a task's name."""
    cids = set().union(*(u.conversations for u in units))
    pids = set().union(*(u.projects for u in units))
    tids = set().union(*(u.scheduled for u in units))
    out: dict[tuple[str, object], str] = {}
    if cids:
        first = (select(func.min(ArslanMessage.id)).where(ArslanMessage.conversation_id.in_(list(cids)),
                                                          ArslanMessage.role == "user")
                 .group_by(ArslanMessage.conversation_id))
        for cid, content in (await db.execute(select(ArslanMessage.conversation_id, ArslanMessage.content)
                                              .where(ArslanMessage.id.in_(first)))).all():
            out[("conversation", cid)] = " ".join((content or "").split())[:TITLE_CHARS]
    if pids:
        for pid, name in (await db.execute(select(Project.id, Project.name).where(Project.id.in_(list(pids))))).all():
            out[("project", pid)] = name
    if tids:
        for tid, name in (await db.execute(select(ScheduledTask.id, ScheduledTask.name)
                                           .where(ScheduledTask.id.in_(list(tids))))).all():
            out[("scheduled_task", tid)] = name
    return out


def _line(units: Waiting, titles: dict, *, why: bool = False) -> dict:
    keys = ([("conversation", cid) for cid in sorted(units.conversations)] + [("project", pid) for pid in sorted(units.projects)]
            + [("scheduled_task", tid) for tid in sorted(units.scheduled)])
    items = [{"kind": kind, "id": ident, "title": titles.get((kind, ident), ""),
              **({"why": units.why.get((kind, ident), "")} if why else {})} for kind, ident in keys[:LIST_CAP]]
    return {"count": units.count, "items": items, "more": max(0, units.count - LIST_CAP)}


async def brief(db: AsyncSession, *, hide_private: bool = False) -> dict:
    """The four lines of Progress's brief, from the records only: each count, the units to open (at most LIST_CAP, the rest in
    `more`) and a template sentence per line that says its count and no other number (v0.1.64: no model writes it).
    `hide_private` (the model's tool): without the conversations another conversation's model may not be shown (`private`)."""
    hide = {"hide_private": hide_private}
    lines = {"done_today": await done_today(db, **hide), "running": await running_now(db, **hide),
             "stuck": await stuck(db, **hide), "waiting_on_you": await waiting_on_user(db, **hide)}
    titles = await _titles(db, list(lines.values()))
    out = {key: _line(units, titles, why=key == "stuck") for key, units in lines.items()}
    out["lines"] = [f"Done today: {lines['done_today'].count}.", f"Running now: {lines['running'].count}.",
                    f"Stuck: {lines['stuck'].count}.", f"Waiting on you: {lines['waiting_on_you'].count}."]
    out["note"] = ("Counts are conversations, projects and scheduled tasks, not messages or runs. Today starts at local "
                   "midnight. Say the counts as given; an item opens by its kind and id."
                   + (" Temporary, no-memory and quick conversations are left out." if hide_private else ""))
    return out
