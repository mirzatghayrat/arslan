"""Enrolled machines: list, enrol, revoke, and the audit trail (spec P3c).

Enrolment lands HERE and only here. The tool that proposes it writes nothing —
it paints a card, and the card's button calls this endpoint. That is the same
division `propose_connect_mcp` uses, and it is what makes "enrolment is an
explicit human action" true of the code rather than a thing the docs assert.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.services import settings_service, ssh_exec, ssh_nodes

router = APIRouter(dependencies=[Depends(require_auth)])


class EnrollIn(BaseModel):
    name: str
    host: str
    user: str
    #: What the user was shown on the card. Sent back so the server can refuse if
    #: the machine now presents something else — see enroll_node for why.
    fingerprints: list[str] = []


def _out(node) -> dict:
    return {"id": node.id, "name": node.name, "host": node.host,
            "user": node.username,
            "fingerprints": ssh_nodes.pinned_fingerprints(node),
            "created_at": node.created_at.isoformat() if node.created_at else None,
            "last_used_at": node.last_used_at.isoformat() if node.last_used_at else None}


@router.get("/ssh-nodes", response_model=dict)
async def list_ssh_nodes(db: AsyncSession = Depends(get_session)) -> dict:
    return {"nodes": [_out(n) for n in await ssh_nodes.list_nodes(db)],
            "enabled": await settings_service.ssh_enabled(db)}


@router.post("/ssh-nodes", response_model=dict)
async def enroll_ssh_node(body: EnrollIn, db: AsyncSession = Depends(get_session)) -> dict:
    if not await settings_service.ssh_enabled(db):
        raise HTTPException(status_code=400, detail="SSH reach is turned off")
    name = (body.name or "").strip()
    host = (body.host or "").strip()
    user = (body.user or "").strip()
    if not name or len(name) > 60:
        raise HTTPException(status_code=400, detail="give the machine a short name")
    if not ssh_exec.is_valid_host(host):
        raise HTTPException(status_code=400, detail="host must be an IPv4 address")
    if not ssh_exec.is_valid_user(user):
        raise HTTPException(status_code=400, detail="invalid remote username")
    if await ssh_nodes.by_name(db, name):
        raise HTTPException(status_code=409, detail=f"'{name}' is already enrolled")
    if await ssh_nodes.by_host(db, host):
        raise HTTPException(status_code=409, detail=f"{host} is already enrolled")

    scan = await ssh_exec.probe(host)
    if not scan.get("ok"):
        raise HTTPException(status_code=502, detail=scan.get("error") or "could not reach it")

    # The user approved a SPECIFIC machine — the one whose fingerprint was on the
    # card. Between that card and this click the address could be answered by
    # something else, so what they approved is checked against what is there now.
    # Re-probing and trusting whatever answers would make the fingerprint on the
    # card decorative.
    live = set(scan.get("fingerprints") or [])
    shown = {f for f in (body.fingerprints or []) if f}
    if shown and not (shown & live):
        raise HTTPException(
            status_code=409,
            detail="that machine is presenting a different host key than the one you "
                   "were shown. Nothing was enrolled.")

    node = await ssh_nodes.enroll(db, name=name, host=host, username=user,
                                  host_keys=scan["keys"],
                                  fingerprints=scan.get("fingerprints") or [])
    return _out(node)


@router.delete("/ssh-nodes/{node_id}", response_model=dict)
async def revoke_ssh_node(node_id: int, db: AsyncSession = Depends(get_session)) -> dict:
    """Forget a machine. Two things this deliberately does not do, both surfaced
    in the UI: it does not delete Arslan's SSH identity (that keypair is shared
    with every other enrolled machine), and it cannot remove the authorized_keys
    line on the far side — only the person with access to that machine can."""
    if not await ssh_nodes.revoke(db, node_id):
        raise HTTPException(status_code=404, detail="no such machine")
    return {"ok": True, "id": node_id}


@router.get("/ssh-audit", response_model=dict)
async def list_ssh_audit(limit: int = ssh_nodes.AUDIT_PAGE,
                         db: AsyncSession = Depends(get_session)) -> dict:
    rows = await ssh_nodes.recent(db, limit=max(1, min(limit, 500)))
    return {"entries": [
        {"id": r.id, "at": r.created_at.isoformat() if r.created_at else None,
         "node_name": r.node_name, "host": r.host, "user": r.username,
         "command": r.command, "exit_code": r.exit_code, "ok": bool(r.ok),
         "error": r.error, "conversation_id": r.conversation_id}
        for r in rows]}
