"""Settings › iPhone (docs/specs/mobile-bridge-protocol.md §6.1): the connected Bridge, paired
phones, a new pairing code, accepting or declining a request, revoking a phone. Behind the
API token like every setting; accepting is the user's click in Arslan's window.

And what the Bridge reads for a paired phone (§5.3): the conversation list, a conversation's
history, and the files Arslan made — a run's artifacts, immutable snapshots with their size and
SHA-256, so the reference the phone holds always matches the bytes it later fetches."""
from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import ArslanMessage, Run
from server.db.session import get_session
from server.services import artifact_store
from server.services.phone_bridge import BridgeUnavailable, hub

router = APIRouter(dependencies=[Depends(require_auth)])

#: A file travels to the phone inside one CloudKit record (protocol §4.6).
PHONE_FILE_MAX = 20 * 1024 * 1024


def _iso(moment: datetime | str | None) -> str:
    """The protocol's timestamps: UTC, whole seconds, "Z" (rows are stored as naive UTC)."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if moment is None:
        return "1970-01-01T00:00:00Z"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_reference(item: dict) -> dict | None:
    """One run artifact as the phone's file reference (`file.offer` body); None when it is too
    big to travel. The id is the artifact's own filename (`run_<id>_<uuid>_<name>`)."""
    size = item.get("bytes")
    if not isinstance(size, int) or size > PHONE_FILE_MAX:
        return None
    filename = item["filename"]
    return {"id": filename, "name": PurePosixPath(item.get("title") or filename).name or filename,
            "size": size, "mime_type": item.get("media_type") or "application/octet-stream",
            "sha256": item["sha256"]}


def run_files(run_id: int | None) -> list[dict]:
    if not run_id:
        return []
    return [ref for ref in map(file_reference, artifact_store.list_artifacts(run_id)) if ref]


class Decision(BaseModel):
    accept: bool


@router.get("/phone")
async def phone_status():
    return hub.status()


@router.post("/phone/pairing")
async def new_pairing_code():
    try:
        return await hub.request_code()
    except BridgeUnavailable:
        raise HTTPException(503, "bridge_unavailable") from None


@router.post("/phone/requests/{request_id}")
async def decide(request_id: str, body: Decision):
    try:
        if not await hub.decide(request_id, body.accept):
            raise HTTPException(404, "request_not_found")
    except BridgeUnavailable:
        raise HTTPException(503, "bridge_unavailable") from None
    return {"request_id": request_id, "accepted": body.accept}


@router.delete("/phone/devices/{device_id}")
async def revoke(device_id: str):
    try:
        if not await hub.revoke(device_id):
            raise HTTPException(404, "device_not_found")
    except BridgeUnavailable:
        raise HTTPException(503, "bridge_unavailable") from None
    return {"device_id": device_id, "revoked": True}


@router.get("/phone/conversations")
async def phone_conversations(limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_session)):
    """`conversations.result`: most recently active first, the same list as the window's sidebar."""
    from server.api.conversations import list_conversations
    rows = (await list_conversations(db))[:limit]
    return {"conversations": [{"id": r.conversation_id, "title": r.title, "updated_at": _iso(r.last_at)}
                              for r in rows]}


@router.get("/phone/conversations/{conversation_id}/history")
async def phone_history(conversation_id: str, limit: int = Query(50, ge=1, le=200),
                        db: AsyncSession = Depends(get_session)):
    """`chat.history.result`: the latest `limit` messages, oldest first. Ids are the message ids
    the Mac's final `chat.event` uses too, so the phone can merge the two. Arslan's replies carry
    the files their run made."""
    rows = (await db.execute(
        select(ArslanMessage).where(ArslanMessage.conversation_id == conversation_id)
        .order_by(ArslanMessage.id.desc()).limit(limit))).scalars().all()
    return {"conversation_id": conversation_id, "messages": [
        {"id": str(m.id), "role": "user" if m.role == "user" else "assistant",
         "text": m.display_content or m.content, "ts": _iso(m.timestamp),
         "attachments": run_files(m.run_id)}
        for m in reversed(rows)]}


@router.get("/phone/runs/{run_id}/files")
async def phone_run_files(run_id: int, db: AsyncSession = Depends(get_session)):
    """The files one turn made, offered to the phone when the turn ends (its stream_end names the run)."""
    if await db.get(Run, run_id) is None:
        raise HTTPException(404, "run_not_found")
    return {"files": run_files(run_id)}


@router.get("/phone/files/{file_id}")
async def phone_file(file_id: str, db: AsyncSession = Depends(get_session)):
    """`file.get`: the bytes of one artifact, checked against its manifest (size and SHA-256)
    before they leave. Only an artifact of a run that exists, as with the window's download."""
    match = re.fullmatch(r"run_(\d+)_.+", file_id)
    if match is None or await db.get(Run, int(match.group(1))) is None:
        raise HTTPException(404, "file_unavailable")
    try:
        metadata, data = artifact_store.read_owned(int(match.group(1)), file_id)
    except (OSError, ValueError):
        raise HTTPException(404, "file_unavailable") from None
    reference = file_reference(metadata)
    if reference is None:
        raise HTTPException(413, "too_large")
    return {"file": reference, "data": base64.b64encode(data).decode()}
