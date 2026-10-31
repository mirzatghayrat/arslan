"""INB5 (v0.1.64): what is waiting on you, counted once.

The INB card's one function: the badge reads it now, and INB7's brief ("要你做"), INB8's push and the phone are to read it too,
never a count of their own. A unit is a conversation, a project or a scheduled task, never a row:
- a conversation waits when it has a card to approve, something it could not ask while you were away that is newer than your last
  look at it (Q8, approved with the INB5 board on 2026-10-31: opening it is "handled"; the entry stays listed until it expires),
  or an open "the job stopped" reminder. Only conversations that still exist count (a deleted one keeps its ledger rows and
  reminders; #590 review F2), except a pending card, which is live by definition;
- a conversation in an active project counts as its project. One in an archived project counts by itself: that project has no
  row in the sidebar, where its conversations are listed under 「最近」 (#590 review F3c). INB5b makes the sidebar show every project
  that has something waiting, so a counted project always has a row even below its top few;
- a scheduled task waits when its last run failed or it paused itself, it has an open problem reminder, or one of its runs could not
  ask something newer than your last look at the task (`scheduled_tasks.seen_at`, migration 0084, set when you open the task).
  The task's own conversation (`scheduled-<id>`) counts as the task: one thing, counted once (#590 review F4).

The window's conversation list reads `waiting_conversations` too (phone_reads.describe marks those rows "waiting"), so every
conversation the badge counts has a marked row (#590 review F3a). INB5b moves the Scheduled page's dot onto `waiting.scheduled`,
so the dot and the badge follow one rule (#590 review F3b).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.companion_models import ConversationContext, Project
from server.db.models import ApprovalEvent, ArslanMessage, ConversationSeen, ProactiveItem, ScheduledTask, ScheduledTaskRun
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

    @property
    def count(self) -> int:
        return len(self.conversations) + len(self.projects) + len(self.scheduled)

    def as_dict(self) -> dict:
        return {"count": self.count, "conversations": sorted(self.conversations), "projects": sorted(self.projects),
                "scheduled": sorted(self.scheduled)}


async def _latest_not_asked(db: AsyncSession, decided_by: str, hours: int) -> dict[str, datetime]:
    """Per conversation, the newest entry of one kind of "could not ask": `away` (a card that never opened) or `policy` (a
    scheduled run). Kept apart: a scheduled run's entry belongs to its task, not to the conversation it writes into."""
    decision = {"away": "expired", "policy": "deny"}[decided_by]
    rows = await db.execute(select(ApprovalEvent.conversation_id, func.max(ApprovalEvent.created_at))
                            .where(ApprovalEvent.decided_by == decided_by, ApprovalEvent.decision == decision,
                                   ApprovalEvent.conversation_id.is_not(None),
                                   ApprovalEvent.created_at >= datetime.utcnow() - timedelta(hours=hours))
                            .group_by(ApprovalEvent.conversation_id))
    return dict(rows.all())


async def waiting_conversations(db: AsyncSession) -> set[str]:
    """The conversations waiting on you, before projects and tasks group them."""
    pending = {card["conversation_id"] for card in approvals.all_pending() if card.get("conversation_id")}
    away = await _latest_not_asked(db, "away", AWAY_HOURS)
    seen = dict((await db.execute(select(ConversationSeen.conversation_id, ConversationSeen.seen_at)
                                  .where(ConversationSeen.conversation_id.in_(list(away))))).all()) if away else {}
    candidates = {cid for cid, latest in away.items() if cid not in seen or latest > seen[cid]}
    candidates |= set((await db.execute(select(ProactiveItem.conversation_id).where(
        ProactiveItem.kind == "job_followup", ProactiveItem.status.in_(OPEN),
        ProactiveItem.conversation_id.is_not(None)))).scalars())
    existing = set((await db.execute(select(ArslanMessage.conversation_id).distinct()
                                     .where(ArslanMessage.conversation_id.in_(list(candidates))))).scalars()) if candidates else set()
    return pending | existing


async def waiting_on_user(db: AsyncSession) -> Waiting:
    out = Waiting()
    asking = await waiting_conversations(db)
    tasks = list((await db.execute(select(ScheduledTask))).scalars())
    own = {f"scheduled-{task.id}": task.id for task in tasks}
    out.scheduled |= {own[cid] for cid in asking if cid in own}
    asking = {cid for cid in asking if cid not in own}

    project_of = dict((await db.execute(select(ConversationContext.id, ConversationContext.project_id)
                                        .join(Project, Project.id == ConversationContext.project_id)
                                        .where(ConversationContext.id.in_(asking), Project.status != "archived"))).all())
    for cid in asking:
        if cid in project_of:
            out.projects.add(project_of[cid])
        else:
            out.conversations.add(cid)

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
