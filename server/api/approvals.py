"""Pending confirmation cards, answerable from anywhere in the app (0.1.55).

The Inbox ("现在就要你批准") lists every card waiting for the user — a window's own
turn, a background job, a turn the iPhone started — and answers one by call_id.
The reply is built from the card's own kind (`approvals.answer_by_id`), so this
route can only ever confirm or cancel THAT card; it cannot widen a permission.

0.1.61 §A4: an answer carries a scope — one of the choices the card offered (the island's yes is
its first choice: `approvals.answer` clamps it, never this route) — and, on No, a note. The Inbox
also lists what could not be asked ("Not done while you were away": a run with nobody to ask, and
the cards a job or a turn did not open once one went unanswered), with what "Always allow" will
store and the button for it (`POST /permissions/rules {refused_id}`).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.services import approvals, permission_store, permissions

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/approvals/pending")
async def list_pending() -> list[dict]:
    return approvals.all_pending()


class Answer(BaseModel):
    approve: bool
    source: Literal["inbox", "island"] = "inbox"
    scope: Literal["once", "task", "conversation", "always"] | None = None
    note: str = ""


@router.post("/approvals/{call_id}/answer")
async def answer(call_id: str, body: Answer) -> dict:
    # "remember" is never sent from here: the scope is chosen on the card itself.
    try:
        answered = approvals.answer_by_id(call_id, body.approve, source=body.source,
                                          scope=body.scope, note=body.note)
    except approvals.OpenInArslan as exc:
        raise HTTPException(status_code=403, detail={"code": "open_in_arslan"}) from exc
    if not answered:
        raise HTTPException(status_code=404, detail="no such pending card (answered or expired)")
    return {"ok": True}


#: At most this many "not done" groups are listed.
REFUSED_GROUPS = 100


@router.get("/approvals/refused")
async def list_refused(hours: int = 24, conversation_id: str | None = Query(None, min_length=1, max_length=100),
                       db: AsyncSession = Depends(get_session)) -> list[dict]:
    """What could not be asked (`permission_store.NOT_ASKED`), the last `hours` (1 to 168): what
    a run with nobody to ask refused (a scheduled run: `decided_by` policy, `unattended` true), and the
    cards of a job or a chat turn that never opened because an earlier one went unanswered (the person
    is away: `decided_by` away, an expiry). One entry per kind, target and which of the two — its latest row (`id` is what
    "Always allow" sends back), how many times (`count`) and since when (`first_at`) — newest
    first, at most `REFUSED_GROUPS`. `always_ok`: the card would have offered "Always" (its row
    recorded the set). `always` (0.1.61, F2): what "Always allow" will store, exactly the rules
    `POST /permissions/rules {refused_id: id}` makes — `[{kind, target, label}]`, each label the
    words its card used; empty when `always_ok` is false. The Inbox shows it before the click.
    An entry whose "Always" set is all allowed already is left out. `conversation_id` (INB3): only that
    conversation's (a scheduled task's is `task.conversation_id` or `scheduled-<id>`)."""
    hours = max(1, min(168, hours))
    since = datetime.utcnow() - timedelta(hours=hours)
    groups = await permission_store.refused_groups(db, since, conversation_id=conversation_id)
    rules = {(r.kind, r.target) for r in await permission_store.list_rules(db)}
    out = []
    for row, count, first in groups:
        always = permissions.always_from(row.extra)
        if always and all((kind, target) in rules for kind, target, _ in always):
            continue                            # allowed since: nothing is waiting any more
        out.append({"id": row.id, "created_at": _utc(row.created_at), "first_at": _utc(first),
                    "count": count, "conversation_id": row.conversation_id, "kind": row.kind,
                    "target": row.target, "detail": row.detail, "always_ok": bool(always),
                    "unattended": row.decided_by == "policy",
                    "always": [{"kind": kind, "target": target, "label": label}
                               for kind, target, label in always]})
        if len(out) == REFUSED_GROUPS:
            break
    return out


def _utc(moment: datetime | None) -> str | None:
    """The store keeps naive UTC: say so, or a browser reads it as local time."""
    return moment.isoformat() + "Z" if moment is not None else None
