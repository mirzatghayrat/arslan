"""INB5 (v0.1.64): what is waiting on you, counted once.

The INB card's one function: the badge reads it now, and INB7's brief ("要你做"), INB8's push and the phone are to read it too,
never a count of their own. A unit is a conversation, a project or a scheduled task, never a row:
- a conversation waits when it has a card to approve, something it could not ask while you were away that is newer than your last
  look at it (Q8, approved with the INB5 board on 2026-10-31: opening it is "handled"; the entry stays listed until it expires),
  or an open "the job stopped" reminder; a conversation in a project counts as its project;
- a scheduled task waits when its last run failed or it paused itself, it has an open problem reminder, or one of its runs could not
  ask something newer than your last look at it (its `scheduled-<id>` seen mark, the INB4 table).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.companion_models import ConversationContext
from server.db.models import ApprovalEvent, ConversationSeen, ProactiveItem, ScheduledTask, ScheduledTaskRun
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


async def waiting_on_user(db: AsyncSession) -> Waiting:
    seen = dict((await db.execute(select(ConversationSeen.conversation_id, ConversationSeen.seen_at))).all())

    def newer(key: str, latest: datetime) -> bool:
        return key not in seen or latest > seen[key]

    asking: set[str] = {card["conversation_id"] for card in approvals.all_pending() if card.get("conversation_id")}
    asking |= {cid for cid, latest in (await _latest_not_asked(db, "away", AWAY_HOURS)).items() if newer(cid, latest)}
    asking |= set((await db.execute(select(ProactiveItem.conversation_id).where(
        ProactiveItem.kind == "job_followup", ProactiveItem.status.in_(OPEN),
        ProactiveItem.conversation_id.is_not(None)))).scalars())

    out = Waiting()
    project_of = dict((await db.execute(select(ConversationContext.id, ConversationContext.project_id).where(
        ConversationContext.id.in_(asking), ConversationContext.project_id.is_not(None)))).all())
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
    for task in (await db.execute(select(ScheduledTask))).scalars():
        conversation = task.conversation_id or f"scheduled-{task.id}"
        if (task.paused_reason is not None or last_outcome.get(task.id) == "error" or str(task.id) in problems
                or (conversation in unasked and newer(f"scheduled-{task.id}", unasked[conversation]))):
            out.scheduled.add(task.id)
    return out
