"""Pending confirmation cards, answerable from anywhere in the app (0.1.55).

The Inbox ("现在就要你批准") lists every card waiting for the user — a window's own
turn, a background job, a turn the iPhone started — and answers one by call_id.
The reply is built from the card's own kind (`approvals.answer_by_id`), so this
route can only ever confirm or cancel THAT card; it cannot widen a permission.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
from server.services import approvals

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/approvals/pending")
async def list_pending() -> list[dict]:
    return approvals.all_pending()


class Answer(BaseModel):
    approve: bool
    source: Literal["inbox", "island"] = "inbox"


@router.post("/approvals/{call_id}/answer")
async def answer(call_id: str, body: Answer) -> dict:
    # "remember" is never offered from here: a remembered rule is chosen on the card itself.
    try:
        answered = approvals.answer_by_id(call_id, body.approve, source=body.source)
    except approvals.OpenInArslan as exc:
        raise HTTPException(status_code=403, detail={"code": "open_in_arslan"}) from exc
    if not answered:
        raise HTTPException(status_code=404, detail="no such pending card (answered or expired)")
    return {"ok": True}
