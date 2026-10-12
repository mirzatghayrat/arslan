"""Standing answers ("Always" rules), listed, added and withdrawn (0.1.61 §A5).

Settings → What Arslan may do lists them, each removable; the Inbox's "Always allow" on what a run
with nobody to ask could not do (`GET /approvals/refused`) adds one. A kind that is never
remembered (`permissions._NEVER_ALWAYS`: money, a new capability, another agent's settings, a
deletion, a takeover, a schedule…) never becomes a rule here either: no card offers it "Always",
and this route is no way around that.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import PermissionRule
from server.db.session import get_session
from server.services import permission_store, permissions, terminal_policy

router = APIRouter(dependencies=[Depends(require_auth)])

#: A rule's target: a bundle id, a path, a host, a command's rules.
_TARGET_CHARS = 2000
#: How a many-app card's ledger row joins its targets (`permissions.decide_many`).
_JOINED = "\x1e"


class NewRule(BaseModel):
    kind: str
    target: str
    label: str = ""


@router.get("/permissions/rules")
async def list_rules(db: AsyncSession = Depends(get_session)) -> list[dict]:
    return [_out(row) for row in await permission_store.list_rules(db)]


@router.post("/permissions/rules")
async def add_rule(body: NewRule, db: AsyncSession = Depends(get_session)) -> dict:
    """The rule for (kind, target), or 400. A target joined from a many-app card's row is one rule
    per target, each with its own label when the label is joined the same way (else its target).
    Returns the first rule, and every one made under `rules`."""
    targets = _targets(body.kind, body.target)
    labels = body.label.split(_JOINED)
    if len(labels) != len(targets):
        labels = targets                 # one label for several apps would misname every one
    rules: dict[str, str] = {}
    for target, label in zip(targets, labels):
        rules.setdefault(target, label)  # a target named twice is one rule, with its first label
    rows = [await permission_store.add_rule(db, body.kind, target, label=label,
                                            created_from="settings")
            for target, label in rules.items()]
    await db.commit()
    return {**_out(rows[0]), "rules": [_out(row) for row in rows]}


@router.delete("/permissions/rules/{rule_id}")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    if not await permission_store.delete_rule(db, rule_id):
        raise HTTPException(status_code=404, detail="no such rule")
    await db.commit()
    return {"ok": True}


def _targets(kind: str, target: str) -> list[str]:
    """What may become a rule: never a kind that is never remembered, never an empty target or
    one over 2000 characters — of each target, when several are joined (fail closed: one bad part
    refuses the whole)."""
    if kind in permissions._NEVER_ALWAYS:
        raise HTTPException(status_code=400, detail={"code": "never_remembered", "kind": kind})
    if not kind.strip() or len(kind) > 30 or len(target) > permissions._TARGET_MAX:
        raise HTTPException(status_code=400, detail={"code": "bad_rule"})
    parts = target.split(_JOINED)
    if any(not part.strip() or len(part) > _TARGET_CHARS for part in parts):
        raise HTTPException(status_code=400, detail={"code": "bad_target"})
    return parts


def _out(row: PermissionRule) -> dict:
    # A rule carried over from 0.1.60 has no label: it is listed in the words its card used.
    label = row.label or (terminal_policy.describe(row.target) if row.kind == "legacy_rule" else "")
    return {"id": row.id, "kind": row.kind, "target": row.target, "label": label,
            "created_at": _utc(row.created_at), "last_used_at": _utc(row.last_used_at),
            "use_count": row.use_count or 0}


def _utc(moment: datetime | None) -> str | None:
    """The store keeps naive UTC: say so, or a browser reads it as local time."""
    return moment.isoformat() + "Z" if moment is not None else None
