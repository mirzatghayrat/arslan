"""Where Arslan's permissions are kept (0.1.61 §A5, §A8).

Standing answers ("Always", `PermissionRule`), answers for one task or one conversation
(`PermissionGrant`), and the ledger of every decision that crossed a boundary
(`ApprovalEvent`). Plain storage: what a request means and when to ask is `permissions`'
business. Nothing here commits — the caller owns the transaction.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from server.db.models import ApprovalEvent, PermissionGrant, PermissionRule

#: Ledger rows are kept this long (spec §A8).
LEDGER_DAYS = 90
#: The ledger rows of what could not be asked, as (decided_by, decision): the Inbox lists them, an
#: away one with "Always allow" for next time (§A4, `refused_groups`), a scheduled run's never (S1).
#: - ("policy", "deny"): refused because the run had nobody to ask (a scheduled run);
#: - ("away", "expired"): a card that never opened because the person is away — an earlier card
#:   of the same job or chat turn went unanswered (0.1.61, F3). An expiry, never a denial: a
#:   count of the user's "no" (decided_by "user", decision "deny") never includes it, and a card
#:   that was shown and ran out ("expired", "expired") is not one of these.
NOT_ASKED = (("policy", "deny"), ("away", "expired"))
#: A task grant's turn or job never comes back; its row is pruned after this.
TASK_GRANT_HOURS = 24
#: Pruning runs at most once an hour, on a write.
_PRUNE_EVERY_S = 3600
_last_prune = {"at": 0.0}


async def find_rule(db, kind: str, target: str) -> PermissionRule | None:
    return (await db.execute(select(PermissionRule).where(
        PermissionRule.kind == kind, PermissionRule.target == target))).scalar_one_or_none()


async def add_rule(db, kind: str, target: str, *, label: str = "",
                   created_from: str = "") -> PermissionRule:
    """The rule for (kind, target), added if it is not there yet. Another session adding the
    same one at the same moment is fine: whichever insert comes second does nothing, and both
    get the one row. (An insert, even one that does nothing, holds SQLite's write lock until
    the caller commits, so nobody can delete the row before it is read back.)"""
    await db.execute(sqlite_insert(PermissionRule).values(
        kind=kind, target=target, label=label[:500], created_from=created_from[:80],
        created_at=datetime.utcnow(), use_count=0,
    ).on_conflict_do_nothing(index_elements=["kind", "target"]))
    return await find_rule(db, kind, target)


async def touch_rule(db, row: PermissionRule) -> None:
    row.last_used_at = datetime.utcnow()
    row.use_count = (row.use_count or 0) + 1


async def list_rules(db, kind: str | None = None) -> list[PermissionRule]:
    query = select(PermissionRule).order_by(PermissionRule.created_at.desc(), PermissionRule.id.desc())
    if kind is not None:
        query = query.where(PermissionRule.kind == kind)
    return list((await db.execute(query)).scalars().all())


async def delete_rule(db, rule_id: int) -> bool:
    row = await db.get(PermissionRule, rule_id)
    if row is None:
        return False
    await db.delete(row)
    return True


async def delete_rule_by(db, kind: str, target: str) -> bool:
    row = await find_rule(db, kind, target)
    if row is None:
        return False
    await db.delete(row)
    return True


async def find_grant(db, conversation_id: str | None, task_id: str | None, kind: str,
                     target: str) -> PermissionGrant | None:
    """A conversation grant (task_id "") or a grant for exactly this task."""
    if not conversation_id:
        return None
    tasks = [""] + ([task_id] if task_id else [])
    return (await db.execute(select(PermissionGrant).where(
        PermissionGrant.conversation_id == conversation_id,
        PermissionGrant.task_id.in_(tasks),
        PermissionGrant.kind == kind,
        PermissionGrant.target == target).limit(1))).scalar_one_or_none()


async def add_grant(db, conversation_id: str, task_id: str, kind: str, target: str, *,
                    call_id: str = "") -> PermissionGrant:
    await _prune(db)
    task_id = task_id or ""
    await db.execute(sqlite_insert(PermissionGrant).values(
        conversation_id=conversation_id, task_id=task_id, kind=kind, target=target,
        call_id=call_id[:64], created_at=datetime.utcnow(),
    ).on_conflict_do_nothing(
        index_elements=["conversation_id", "task_id", "kind", "target"]))
    # Exactly this key, not find_grant's "this task or the whole conversation".
    return (await db.execute(select(PermissionGrant).where(
        PermissionGrant.conversation_id == conversation_id, PermissionGrant.task_id == task_id,
        PermissionGrant.kind == kind, PermissionGrant.target == target))).scalar_one()


async def list_conversation_grants(db, kind: str | None = None) -> list[PermissionGrant]:
    """Every "in this conversation" grant (task_id ""), newest first; of one kind when `kind` is given.
    A task's grants end with it, so they are not listed."""
    query = select(PermissionGrant).where(PermissionGrant.task_id == "")
    if kind is not None:
        query = query.where(PermissionGrant.kind == kind)
    return list((await db.execute(query.order_by(PermissionGrant.id.desc()))).scalars().all())


async def delete_conversation_grant(db, grant_id: int) -> bool:
    """Take back one "in this conversation" grant. A task's grant is not one: it ends with its task."""
    result = await db.execute(delete(PermissionGrant).where(
        PermissionGrant.id == grant_id, PermissionGrant.task_id == ""))
    return bool(result.rowcount)


async def delete_task_grants(db, task_id: str) -> int:
    """Every grant for this one task (a turn or a job). A conversation grant (task_id "") is never
    one of them, so an empty id deletes nothing."""
    if not task_id:
        return 0
    result = await db.execute(delete(PermissionGrant).where(PermissionGrant.task_id == task_id))
    return result.rowcount or 0


async def delete_every_task_grant(db) -> int:
    """Every "for this task" grant, of every task (task_id not ""): what boot drops, since no turn
    or job survives a restart. The conversation grants stay."""
    result = await db.execute(delete(PermissionGrant).where(PermissionGrant.task_id != ""))
    return result.rowcount or 0


async def record(db, **fields) -> ApprovalEvent:
    await _prune(db)
    row = ApprovalEvent(created_at=datetime.utcnow(), **fields)
    db.add(row)
    await db.flush()
    return row


async def recent(db, *, limit: int = 200) -> list[ApprovalEvent]:
    return list((await db.execute(select(ApprovalEvent).order_by(
        ApprovalEvent.created_at.desc(), ApprovalEvent.id.desc()).limit(limit))).scalars().all())


def could_not_ask(row: ApprovalEvent) -> bool:
    """Whether this ledger row is one of `NOT_ASKED`: what the Inbox lists, and the only kind of
    row "Always allow" may be given for."""
    return (row.decided_by, row.decision) in NOT_ASKED


def _not_asked():
    return or_(*(and_(ApprovalEvent.decided_by == decided_by, ApprovalEvent.decision == decision)
                 for decided_by, decision in NOT_ASKED))


async def refused_groups(db, since: datetime, *, limit: int = 500, conversation_id: str | None = None
                         ) -> list[tuple[ApprovalEvent, int, datetime]]:
    """Boundaries that could not be asked (`NOT_ASKED`) since `since`: a run with nobody to ask (a
    scheduled run), or a card that never opened while the person was away. One entry per (kind,
    target, who refused it): its latest row, how many times it was refused, and when first — newest
    first, at most `limit` groups. The Inbox offers "Always allow" for next time over an away entry
    (spec §A4); never over a scheduled run's, which no "Always" answers (S1, ⓪Plan's review: grouped
    together, an away row's set would have been offered over both).

    `conversation_id` (INB3): only that conversation's rows, picked before grouping. Grouped first, two
    conversations that refused the same thing would make one group whose latest row names one of them."""
    where = [_not_asked(), ApprovalEvent.created_at >= since]
    if conversation_id is not None:
        where.append(ApprovalEvent.conversation_id == conversation_id)
    groups = (await db.execute(
        select(func.max(ApprovalEvent.id), func.count(), func.min(ApprovalEvent.created_at))
        .where(*where)
        .group_by(ApprovalEvent.kind, ApprovalEvent.target, ApprovalEvent.decided_by)
        .order_by(func.max(ApprovalEvent.id).desc()).limit(limit))).all()
    rows = {row.id: row for row in (await db.execute(select(ApprovalEvent).where(
        ApprovalEvent.id.in_([latest for latest, _, _ in groups])))).scalars().all()}
    return [(rows[latest], count, first) for latest, count, first in groups if latest in rows]


async def _prune(db) -> None:
    now = time.monotonic()
    if _last_prune["at"] and now - _last_prune["at"] < _PRUNE_EVERY_S:
        return
    _last_prune["at"] = now
    cutoff = datetime.utcnow()
    await db.execute(delete(ApprovalEvent).where(
        ApprovalEvent.created_at < cutoff - timedelta(days=LEDGER_DAYS)))
    await db.execute(delete(PermissionGrant).where(
        PermissionGrant.task_id != "",
        PermissionGrant.created_at < cutoff - timedelta(hours=TASK_GRANT_HOURS)))


def _reset_for_tests() -> None:
    _last_prune["at"] = 0.0
