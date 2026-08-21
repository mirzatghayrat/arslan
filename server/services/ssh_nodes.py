"""Enrolled machines and the record of what was done to them (spec P3c).

What enrolment buys, exactly: the user stops re-verifying a fingerprint they
have already verified. What it does NOT buy — by the user's ruling, written into
the code and not only the spec — is any relaxation of the execution gate. Every
`ssh_run` on an enrolled node still asks. An enrolled machine that could be
driven unattended is the persistence-plus-no-human shape both arXiv analyses of
OpenClaw are about; the switch that would produce it is the one we declined.

The pin is the other half. On every run the live host key must still match what
was stored at enrolment, so a machine that has been swapped out is refused by
ssh itself. Trust-on-first-use is a decision a person makes once; making it
again silently, every time, is not the same thing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import SshAudit, SshNode

logger = logging.getLogger(__name__)

#: How many audit rows the API hands back by default. The table is the record;
#: this is only what fits on a screen.
AUDIT_PAGE = 100


async def list_nodes(session: AsyncSession) -> list[SshNode]:
    rows = await session.execute(select(SshNode).order_by(SshNode.name))
    return list(rows.scalars().all())


async def by_host(session: AsyncSession, host: str) -> SshNode | None:
    """The node enrolled for this address, if any. Host is the lookup key rather
    than name because that is what a command names."""
    rows = await session.execute(select(SshNode).where(SshNode.host == host.strip()))
    return rows.scalars().first()


async def by_name(session: AsyncSession, name: str) -> SshNode | None:
    rows = await session.execute(select(SshNode).where(SshNode.name == name.strip()))
    return rows.scalars().first()


async def enroll(session: AsyncSession, *, name: str, host: str, username: str,
                 host_keys: list[str], fingerprints: list[str]) -> SshNode:
    node = SshNode(name=name.strip(), host=host.strip(), username=username.strip(),
                   host_keys="\n".join(host_keys),
                   fingerprints="\n".join(fingerprints))
    session.add(node)
    await session.commit()
    await session.refresh(node)
    return node


async def revoke(session: AsyncSession, node_id: int) -> bool:
    """Forget a machine. Deliberately does NOT touch the SSH identity: that
    keypair is global, so deleting it here would break every other enrolled
    machine to revoke one. It also cannot remove the authorized_keys line on the
    far side — the UI says so, because a user who believes a key is gone when it
    is not is worse off than one who was told to go delete it."""
    node = await session.get(SshNode, node_id)
    if node is None:
        return False
    await session.execute(delete(SshNode).where(SshNode.id == node_id))
    await session.commit()
    return True


def pinned_keys(node: SshNode) -> list[str]:
    return [ln for ln in (node.host_keys or "").splitlines() if ln.strip()]


def pinned_fingerprints(node: SshNode) -> list[str]:
    return [ln for ln in (node.fingerprints or "").splitlines() if ln.strip()]


def key_matches(node: SshNode, live_keys: list[str]) -> bool:
    """Whether the machine answering today is the one that was enrolled.

    Compares the KEY MATERIAL, not the whole known_hosts line: ssh-keyscan output
    can differ in ordering or in which types it returns between runs, and a
    comparison that trips on that would train people to re-enrol — which is
    exactly how a genuine key change gets clicked through. At least one shared
    key is the bar; a machine presenting none of the pinned keys is not it.
    """
    def material(lines):
        out = set()
        for ln in lines:
            parts = ln.split()
            if len(parts) >= 3:
                out.add((parts[-2], parts[-1]))     # (keytype, base64)
        return out
    live = material(live_keys)
    return bool(live) and bool(live & material(pinned_keys(node)))


async def touch(session: AsyncSession, node_id: int) -> None:
    node = await session.get(SshNode, node_id)
    if node is not None:
        node.last_used_at = datetime.utcnow()
        await session.commit()


async def record(session: AsyncSession, *, host: str, username: str, command: str,
                 argv: list[str] | None = None, result: dict | None = None,
                 node: SshNode | None = None, conversation_id: str | None = None) -> None:
    """Write one audit row. Best effort by design — losing the record must not
    fail the command the user already approved — but a failure is logged loudly
    rather than passed over, because silent audit loss is the failure mode that
    makes an audit worthless."""
    result = result or {}
    full = command if not argv else command + " " + json.dumps(argv, ensure_ascii=False)
    row = SshAudit(
        node_id=(node.id if node else None),
        node_name=(node.name if node else None),
        host=host, username=username, command=full,
        exit_code=result.get("exit_code"),
        ok=bool(result.get("ok")),
        error=result.get("error"),
        conversation_id=conversation_id,
    )
    try:
        session.add(row)
        await session.commit()
    except Exception:                      # pragma: no cover - storage failure
        logger.exception("ssh audit row could not be written: %s@%s %r",
                         username, host, full[:120])


async def recent(session: AsyncSession, limit: int = AUDIT_PAGE) -> list[SshAudit]:
    rows = await session.execute(
        select(SshAudit).order_by(SshAudit.created_at.desc(), SshAudit.id.desc()).limit(limit))
    return list(rows.scalars().all())
