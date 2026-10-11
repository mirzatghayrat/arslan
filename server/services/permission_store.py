"""Where Arslan's permissions are kept (0.1.61 §A5, §A8).

Standing answers ("Always", `PermissionRule`), answers for one task or one conversation
(`PermissionGrant`), and the ledger of every decision that crossed a boundary
(`ApprovalEvent`). Plain storage: what a request means and when to ask is `permissions`'
business. Nothing here commits — the caller owns the transaction.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from server.db.models import ApprovalEvent, PermissionGrant, PermissionRule

#: Ledger rows are kept this long (spec §A8).
LEDGER_DAYS = 90
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
    row = await find_rule(db, kind, target)
    if row is None:
        row = PermissionRule(kind=kind, target=target, label=label[:500],
                             created_from=created_from[:80], created_at=datetime.utcnow(),
                             use_count=0)
        db.add(row)
        await db.flush()
    return row


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
    row = (await db.execute(select(PermissionGrant).where(
        PermissionGrant.conversation_id == conversation_id, PermissionGrant.task_id == task_id,
        PermissionGrant.kind == kind, PermissionGrant.target == target))).scalar_one_or_none()
    if row is None:
        row = PermissionGrant(conversation_id=conversation_id, task_id=task_id, kind=kind,
                              target=target, call_id=call_id[:64], created_at=datetime.utcnow())
        db.add(row)
        await db.flush()
    return row


async def record(db, **fields) -> ApprovalEvent:
    await _prune(db)
    row = ApprovalEvent(created_at=datetime.utcnow(), **fields)
    db.add(row)
    await db.flush()
    return row


async def recent(db, *, limit: int = 200) -> list[ApprovalEvent]:
    return list((await db.execute(select(ApprovalEvent).order_by(
        ApprovalEvent.created_at.desc(), ApprovalEvent.id.desc()).limit(limit))).scalars().all())


async def refused_since(db, since: datetime) -> list[ApprovalEvent]:
    """Boundaries refused because nobody could be asked (a scheduled run): the Inbox offers
    "Always allow" for next time (spec §A4)."""
    return list((await db.execute(select(ApprovalEvent).where(
        ApprovalEvent.decided_by == "policy", ApprovalEvent.decision == "deny",
        ApprovalEvent.created_at >= since).order_by(ApprovalEvent.created_at.desc()))).scalars().all())


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
