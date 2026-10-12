"""Pending confirmation cards, answerable from anywhere in the app (0.1.55).

The Inbox ("现在就要你批准") lists every card waiting for the user — a window's own
turn, a background job, a turn the iPhone started — and answers one by call_id.
The reply is built from the card's own kind (`approvals.answer_by_id`), so this
route can only ever confirm or cancel THAT card; it cannot widen a permission.

0.1.61 §A4: an answer carries a scope — one of the choices the card offered (the island's yes is
its first choice: `approvals.answer` clamps it, never this route) — and, on No, a note. The Inbox
also lists what a run with nobody to ask could not do ("Not done while you were away"), with
"Always allow" for next time (`/permissions/rules`).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
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


@router.get("/approvals/refused")
async def list_refused(hours: int = 24, db: AsyncSession = Depends(get_session)) -> list[dict]:
    """What was refused because nobody could be asked (a scheduled run: `decided_by` policy), the
    last `hours` (1 to 168). `always_ok` says whether "Always allow" may be offered: never for a
    kind that is never remembered (`permissions._NEVER_ALWAYS` — money, a schedule, a deletion…)."""
    hours = max(1, min(168, hours))
    rows = await permission_store.refused_since(db, datetime.utcnow() - timedelta(hours=hours))
    return [{"id": row.id, "created_at": _utc(row.created_at),
             "conversation_id": row.conversation_id, "kind": row.kind, "target": row.target,
             "detail": row.detail, "always_ok": row.kind not in permissions._NEVER_ALWAYS}
            for row in rows]


def _utc(moment: datetime | None) -> str | None:
    """The store keeps naive UTC: say so, or a browser reads it as local time."""
    return moment.isoformat() + "Z" if moment is not None else None
