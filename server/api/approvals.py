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
from server.services import approvals, net_policy, permission_store, permissions

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
    is away: `decided_by` away, an expiry; `unopened` true), and (INB8) a card that was shown and expired (`unopened`
    false). One entry per kind, target and which of these — its latest row (`id` is what
    "Always allow" sends back), how many times (`count`) and since when (`first_at`) — newest
    first, at most `REFUSED_GROUPS`. `always_ok`: the card would have offered "Always" (its row
    recorded the set). `always` (0.1.61, F2): what "Always allow" will store, exactly the rules
    `POST /permissions/rules {refused_id: id}` makes — `[{kind, target, label}]`, each label the
    words its card used; empty when `always_ok` is false. The Inbox shows it before the click.
    An entry whose "Always" set is all allowed already is left out. `conversation_id` (INB3): only that
    conversation's (a scheduled task's is `task.conversation_id` or `scheduled-<id>`).

    NET-a (Codex round 1, F7): `sites`, the sites of NET-a's card that "In this conversation" allows in the entry's own
    conversation and that aren't allowed there yet (`POST /permissions/grants {refused_id: id}`), else empty. Once
    they all are, an entry is left out as above. A scheduled run's entry (`decided_by` policy) has none: a run with
    nobody to ask reads no grant (S1), so a grant would look like it fixes that run and wouldn't. It stays listed
    until it ages out, saying the run never takes such a step."""
    hours = max(1, min(168, hours))
    since = datetime.utcnow() - timedelta(hours=hours)
    groups = await permission_store.refused_groups(db, since, conversation_id=conversation_id)
    rules = {(r.kind, r.target) for r in await permission_store.list_rules(db)}
    granted = {(g.conversation_id, g.target) for g in await permission_store.list_conversation_grants(db, "network")}
    out = []
    for row, count, first in groups:
        always = permissions.always_from(row.extra)
        if always and all((kind, target) in rules for kind, target, _ in always):
            continue                            # allowed since: nothing is waiting any more
        # A scheduled run's entry offers no grant (S1: it would not count there).
        named = (net_policy.listed_sites(row.kind, row.target)
                 if row.conversation_id and row.decided_by != "policy" else [])
        sites = [site for site in named if (row.conversation_id, f"network:{site}") not in granted]
        if named and not sites:
            continue                            # the same, for NET-a's sites in their conversation
        out.append({"id": row.id, "created_at": _utc(row.created_at), "first_at": _utc(first),
                    "count": count, "conversation_id": row.conversation_id, "kind": row.kind,
                    "target": row.target, "detail": row.detail, "always_ok": bool(always),
                    "unattended": row.decided_by == "policy",
                    # S6 (S4a follow-up 1): an expiry either way, said two ways: the card never opened because an
                    # earlier one went unanswered (`away`), or it was shown and nobody answered in time.
                    "unopened": row.decided_by == "away",
                    "always": [{"kind": kind, "target": target, "label": label}
                               for kind, target, label in always],
                    "sites": sites})
        if len(out) == REFUSED_GROUPS:
            break
    return out


def _utc(moment: datetime | None) -> str | None:
    """The store keeps naive UTC: say so, or a browser reads it as local time."""
    return moment.isoformat() + "Z" if moment is not None else None
