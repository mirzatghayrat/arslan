"""Standing answers ("Always" rules) and "in this conversation" grants: listed and taken back (0.1.61 §A5, S4a, S6).

S6 (v0.1.64): Settings › What Arslan may do › "Remembered answers" lists both, each with a way to take it back:
`GET /permissions/rules` (the apps allowed for good, which Settings › Hands also lists: the same rows) and
`GET /permissions/grants` (every conversation's grants, by conversation). Nothing is added from that page. A
site's, a Shortcut's and an MCP tool's "Always" is still not offered (`permissions._NEVER_ALWAYS`, the user's
choice of 2026-11-11). The only way to add a rule here is the
Inbox's "Always allow" on something that could not be asked (§A4: a run with nobody to ask, or a
card that never opened while the person was away): the POST names that row (`refused_id`), and
the server stores exactly what "Always" on its card would have stored, as recorded on the ledger
row when it was refused (`permissions.ALWAYS_KEY`). A client
never names a kind or a target: what the model wrote never becomes a rule nobody saw, and a card
that hides "Always" (a kind never remembered, a high-reach app, a command no rule matched) gives
nothing to allow.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePath

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.companion_models import ConversationContext
from server.db.models import ApprovalEvent, ArslanMessage, MCPServer, PermissionGrant, PermissionRule, Tool
from server.db.session import get_session
from server.services import hands_service, permission_store, permissions, sub_sessions

router = APIRouter(dependencies=[Depends(require_auth)])

#: S6: the grant kinds the page has words for, as `what`. A command grant is one of two (`_what`); any other kind
#: is listed as "other", in the target's own words, so a standing yes is never hidden.
_SHOWN = frozenset({"outside", "network", "workspace_write", "schedule", "mcp_tool", "app", "site", "shortcut"})
_MCP_KEY = re.compile(r"mcp_(\d+)__(.+)")


class AllowRefused(BaseModel):
    """ "Always allow" on one refused row: its id, and nothing else."""
    model_config = ConfigDict(extra="forbid")

    refused_id: int


@router.get("/permissions/rules")
async def list_rules(db: AsyncSession = Depends(get_session)) -> list[dict]:
    """Every "Always" rule, newest first, with when it was last used and how often. S6: an app still in the old
    Settings › Hands list becomes its rule first, as Hands' own list does (`hands_service.always_apps`)."""
    await hands_service.migrate_always()
    return [_out(row) for row in await permission_store.list_rules(db)]


@router.post("/permissions/rules")
async def allow_refused(body: AllowRefused, db: AsyncSession = Depends(get_session)) -> dict:
    """The rules "Always" on the refused card would have stored: one per app of a many-app card,
    each under the words its card used — the entry's `always` in `GET /approvals/refused`. 404: no
    such row. 409: the row is not one of what could not be asked (`permission_store.NOT_ASKED`: a
    refusal for want of someone to ask, or a card that never opened while the person was away), or
    its card would not have offered "Always" (S6: a set from before S2a-2 naming a command's
    `legacy_rule` included). Returns the first rule, and every one under `rules`."""
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


@router.get("/permissions/grants")
async def list_grants(kind: str | None = None, db: AsyncSession = Depends(get_session)) -> list[dict]:
    """S4a: the "in this conversation" grants, newest first — `?kind=outside` for the conversations whose
    commands may run outside the sandbox, background tasks' too. Each names its conversation by the
    user's first message there (as the conversation list does).

    S6: and what the page shows for it — `what`, the kind in the page's words (a command grant is `unsandboxed`
    or `command`, one command's text); a readable `name` (that command, the folder's name, the tool, the app, the
    site, the Shortcut; "" when there is nothing to name); an MCP tool's `server` label, with `server_gone` when
    that server was removed; and the block it is listed under, `parent_id` and `parent_title`: the commander's for a
    sub-session's grant (`sub_session`), else its own conversation's. A deleted conversation's grants are not
    listed (#799's tombstone, or a delete begun in this process), nor those of a sub-session under one."""
    grants = await permission_store.list_conversation_grants(db, kind)
    blocks = await _blocks(db, {g.conversation_id for g in grants})
    # #836 review: a grant no request reads today (a 0.1.61–0.1.62 rule card's `command` / `rules:<rules>`, among
    # others: `permissions.grant_is_live`) answers nothing, so it is never listed as one that does.
    grants = [g for g in grants if g.conversation_id in blocks and permissions.grant_is_live(g.kind, g.target)]
    titles = await _titles(db, set(blocks) | set(blocks.values()))
    names = await _names(db, grants)
    return [{"id": g.id, "conversation_id": g.conversation_id, "title": titles.get(g.conversation_id, ""),
             "kind": g.kind, "target": g.target, "created_at": _utc(g.created_at), "what": _what(g), **names[g.id],
             "sub_session": blocks[g.conversation_id] != g.conversation_id, "parent_id": blocks[g.conversation_id],
             "parent_title": titles.get(blocks[g.conversation_id], "")} for g in grants]


@router.delete("/permissions/grants/{grant_id}")
async def delete_grant(grant_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    """S4a: take back one "in this conversation" grant. The next step it covered asks again."""
    if not await permission_store.delete_conversation_grant(db, grant_id):
        raise HTTPException(status_code=404, detail="no such grant")
    await db.commit()
    return {"ok": True}


async def _blocks(db: AsyncSession, conversation_ids: set[str]) -> dict[str, str]:
    """S6: each listed conversation's block, its commander's id for a sub-session and its own otherwise. A deleted
    conversation has none (`sub_sessions.is_deleted`), and neither has a sub-session with a deleted one anywhere up
    its chain (read as `sub_sessions.root_of` reads it, each link checked)."""
    out: dict[str, str] = {}
    for cid in conversation_ids:
        row = await db.get(ConversationContext, cid)
        top, steps, gone = cid, 1, sub_sessions.is_deleted(cid, row)
        while not gone and row is not None and row.kind == sub_sessions.SUB and row.parent_id \
                and steps < sub_sessions.MAX_DEPTH:
            top, steps = row.parent_id, steps + 1
            row = await db.get(ConversationContext, top)
            gone = sub_sessions.is_deleted(top, row)
        if not gone:
            out[cid] = top
    return out


def _what(grant: PermissionGrant) -> str:
    if grant.kind == "command":
        return ("unsandboxed" if grant.target == "unsandboxed:*"
                else "command" if grant.target.startswith("text:") else "other")
    return grant.kind if grant.kind in _SHOWN else "other"


async def _names(db: AsyncSession, grants: list[PermissionGrant]) -> dict[int, dict]:
    """S6: what each grant names, readably (see `list_grants`)."""
    keys = {g.id: _MCP_KEY.fullmatch(g.target) for g in grants if g.kind == "mcp_tool"}
    server_ids = {int(m.group(1)) for m in keys.values() if m}
    servers = dict((await db.execute(select(MCPServer.id, MCPServer.label).where(
        MCPServer.id.in_(server_ids)))).all()) if server_ids else {}
    tools = dict((await db.execute(select(Tool.key, Tool.external_name).where(
        Tool.key.in_([g.target for g in grants if g.id in keys])))).all()) if keys else {}
    apps = await _app_names(db, [g for g in grants if g.kind == "app"])
    out: dict[int, dict] = {}
    for g in grants:
        if g.id in keys:
            key, server = keys[g.id], int(keys[g.id].group(1)) if keys[g.id] else None
            out[g.id] = {"name": tools.get(g.target) or (key.group(2) if key else g.target),
                         "server": servers.get(server, ""), "server_gone": server not in servers}
            continue
        what = _what(g)
        name = (g.target[len("text:"):] if what == "command"
                else PurePath(g.target).name or g.target if what == "workspace_write"
                else apps.get(g.target) or g.target if what == "app"
                else g.target[len("network:"):] if what == "network" and g.target != "network:*"   # NET-a: one site
                else "" if what in ("outside", "unsandboxed", "network", "schedule") else g.target)
        out[g.id] = {"name": name, "server": "", "server_gone": False}
    return out


async def _app_names(db: AsyncSession, grants: list[PermissionGrant]) -> dict[str, str]:
    """An app grant is kept by bundle id: its name is the one its card showed (the ledger row that wrote the grant,
    a many-app card's items included), else its "Always" rule's label; the page falls back to the bundle id."""
    if not grants:
        return {}
    names = {r.target: r.label for r in await permission_store.list_rules(db, "app") if r.label}
    extras = (await db.execute(select(ApprovalEvent.extra).where(
        ApprovalEvent.grant_id.in_([g.id for g in grants])))).scalars().all()
    for extra in extras:
        for item in [extra, *(extra.get("items") or [])] if isinstance(extra, dict) else []:
            if isinstance(item, dict) and isinstance(item.get("bundle_id"), str) and isinstance(item.get("app"), str):
                names[item["bundle_id"]] = item["app"]
    return names


async def _titles(db: AsyncSession, conversation_ids: set[str]) -> dict[str, str]:
    """Each conversation's first message from the user, on one line, cut to 60 characters."""
    if not conversation_ids:
        return {}
    first = select(ArslanMessage.conversation_id, func.min(ArslanMessage.id).label("mid")).where(
        ArslanMessage.role == "user", ArslanMessage.conversation_id.in_(conversation_ids)
    ).group_by(ArslanMessage.conversation_id).subquery()
    rows = (await db.execute(select(first.c.conversation_id, ArslanMessage.content).join(
        ArslanMessage, ArslanMessage.id == first.c.mid))).all()
    return {cid: " ".join((content or "").split())[:60] for cid, content in rows}


def _out(row: PermissionRule) -> dict:
    return {"id": row.id, "kind": row.kind, "target": row.target, "label": row.label or "",
            "created_at": _utc(row.created_at), "last_used_at": _utc(row.last_used_at),
            "use_count": row.use_count or 0}


def _utc(moment: datetime | None) -> str | None:
    """The store keeps naive UTC: say so, or a browser reads it as local time."""
    return moment.isoformat() + "Z" if moment is not None else None
