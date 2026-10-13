"""Standing answers ("Always" rules), listed and withdrawn — and added from one place (0.1.61 §A5).

This API lists them and withdraws them. The Settings page that lists every kind of rule, each
removable, is a later PR: in 0.1.61 the command rules are listed in Settings › What Arslan may do
(`/settings/terminal-rules`) and the `app` rules in Settings › Hands, and no page lists a site's or a
Shortcut's, so their "Always" is not offered at all (`permissions._NEVER_ALWAYS`) until that page
exists. The only way to add a rule here is the
Inbox's "Always allow" on something that could not be asked (§A4: a run with nobody to ask, or a
card that never opened while the person was away): the POST names that row (`refused_id`), and
the server stores exactly what "Always" on its card would have stored, as recorded on the ledger
row when it was refused (`permissions.ALWAYS_KEY`). A client
never names a kind or a target: what the model wrote never becomes a rule nobody saw, and a card
that hides "Always" (a kind never remembered, a high-reach app, a command no rule matched) gives
nothing to allow.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import ApprovalEvent, PermissionRule
from server.db.session import get_session
from server.services import permission_store, permissions, terminal_policy

router = APIRouter(dependencies=[Depends(require_auth)])


class AllowRefused(BaseModel):
    """ "Always allow" on one refused row: its id, and nothing else."""
    model_config = ConfigDict(extra="forbid")

    refused_id: int


@router.get("/permissions/rules")
async def list_rules(db: AsyncSession = Depends(get_session)) -> list[dict]:
    return [_out(row) for row in await permission_store.list_rules(db)]


@router.post("/permissions/rules")
async def allow_refused(body: AllowRefused, db: AsyncSession = Depends(get_session)) -> dict:
    """The rules "Always" on the refused card would have stored: one per app of a many-app card,
    one `legacy_rule` per rule a command matched (§A9), each under the words its card used — the
    entry's `always` in `GET /approvals/refused`. 404: no such row. 409: the row is not one of
    what could not be asked (`permission_store.NOT_ASKED`: a refusal for want of someone to ask,
    or a card that never opened while the person was away), or its card would not have offered
    "Always". Returns the first rule, and every one under `rules`."""
    row = await db.get(ApprovalEvent, body.refused_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such refusal")
    if not permission_store.could_not_ask(row):
        raise HTTPException(status_code=409, detail={"code": "not_a_refusal"})
    always = permissions.always_from(row.extra)
    if not always:
        raise HTTPException(status_code=409, detail={"code": "no_always"})
    rules = [await permission_store.add_rule(db, kind, target, label=label,
                                             created_from=f"refused:{row.id}")
             for kind, target, label in always]
    await db.commit()
    return {**_out(rules[0]), "rules": [_out(rule) for rule in rules]}


@router.delete("/permissions/rules/{rule_id}")
async def delete_rule(rule_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    if not await permission_store.delete_rule(db, rule_id):
        raise HTTPException(status_code=404, detail="no such rule")
    await db.commit()
    return {"ok": True}


def _out(row: PermissionRule) -> dict:
    # A rule carried over from 0.1.60 has no label: it is listed in the words its card used.
    label = row.label or (terminal_policy.describe(row.target) if row.kind == "legacy_rule" else "")
    return {"id": row.id, "kind": row.kind, "target": row.target, "label": label,
            "created_at": _utc(row.created_at), "last_used_at": _utc(row.last_used_at),
            "use_count": row.use_count or 0}


def _utc(moment: datetime | None) -> str | None:
    """The store keeps naive UTC: say so, or a browser reads it as local time."""
    return moment.isoformat() + "Z" if moment is not None else None
