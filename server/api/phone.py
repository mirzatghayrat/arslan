"""Settings › iPhone (docs/specs/mobile-bridge-protocol.md §6.1): the connected Bridge, paired
phones, a new pairing code, accepting or declining a request, revoking a phone. Behind the
API token like every setting; accepting is the user's click in Arslan's window.

And what the Bridge reads for a paired phone (§5.3): the status the phone's home screen shows
(the island's state), the conversation list, a conversation's history, and the files Arslan made — a run's artifacts, immutable snapshots with their size and
SHA-256, so the reference the phone holds always matches the bytes it later fetches.

And, the other way (§5.7, 2026-10-13): a file the phone sent, saved into the workspace's
Inbox/iPhone folder; the conversations the Bridge keeps a live socket on."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.companion_models import ConversationContext
from server.db.models import ArslanMessage, Run
from server.db.session import get_session
from server.services import artifact_store, background_jobs, desktop_status, phone_reads, settings_service
from server.services.phone_bridge import BridgeUnavailable, hub
from server.services.phone_reads import PHONE_FILE_MAX, file_reference, iso as _iso, run_files  # noqa: F401

router = APIRouter(dependencies=[Depends(require_auth)])

#: The island's search tools (`SEARCH_TOOLS` in web/src/island/islandMachine.ts, plus any
#: browser_* tool). A test reads that file, so the two cannot drift apart.
SEARCH_TOOLS = frozenset({"web_search", "web_extract", "recall"})
#: How long a finished or stopped piece of work stays on the phone's mascot.
RESULT_SECONDS = 60


def phone_mascot(feed: dict, now: float) -> str:
    """The island's mood in the phone's words (§5.3 `mascot`), in the island's order: a card
    waiting, then work in flight (searching or working, by the newest run's latest step), then
    what finished in the last minute (done, or stopped when it failed or a schedule paused;
    nothing when you cancelled it), else idle."""
    if feed.get("awaiting"):
        return "approval"
    if feed.get("active"):
        newest = max(feed["active"], key=lambda a: a.get("started_at") or 0)
        tool = (newest.get("step") or {}).get("tool") or ""
        return "searching" if tool in SEARCH_TOOLS or tool.startswith("browser_") else "working"
    for event in reversed(feed.get("events") or []):
        if now - (event.get("at") or 0) > RESULT_SECONDS:
            break
        if event.get("kind") == "scheduled_paused":
            return "stopped"
        if event.get("kind") in ("turn_finished", "scheduled_finished"):
            outcome = event.get("outcome")
            if outcome == "ok":
                return "done"
            return "stopped" if outcome in ("error", "needs_review") else "idle"
    return "idle"


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
async def phone_conversations(limit: int = Query(20, ge=1, le=100), kind: str | None = None,
                              before: str | None = None, db: AsyncSession = Depends(get_session)):
    """`conversations.result`: most recently active first, the same list as the window's sidebar. Q1:
    `kind=quick` lists the quick questions instead (they are never in the other list); `before` pages back
    to conversations at or before that `updated_at`, and `has_more` says whether any remain. Times are whole
    seconds, so the boundary second is included and the phone drops the ids it already has: a strictly-older
    page would skip, for good, one cut by `limit` inside that second (①iOS's review of #479). A page that
    brings the phone nothing new ends its paging."""
    from server.api.conversations import conversation_list
    if kind not in (None, "quick"):
        raise HTTPException(400, "bad_request")
    try:
        older = _iso(before) if before else None
    except ValueError:
        raise HTTPException(400, "bad_request") from None
    rows = [r for r in await conversation_list(db, quick=kind == "quick") if older is None or _iso(r.last_at) <= older]
    return {"conversations": [{"id": r.conversation_id, "title": r.title, "updated_at": _iso(r.last_at),
                               "kind": r.kind, "state": r.state, "origin": r.origin, "preview": r.preview,
                               "files": r.files, **({"job": r.job} if r.job else {})}
                              for r in rows[:limit]],
            "has_more": len(rows) > limit}


#: Q1: a quick question's id, made on the phone (`phone-` and a lowercase UUID v4; card, detail A).
_QUICK_ID = re.compile(r"phone-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


@router.post("/phone/conversations/{conversation_id}/quick")
async def phone_new_quick(conversation_id: str, db: AsyncSession = Depends(get_session)):
    """Q1: store a new conversation as a quick question before its first message runs, so that turn
    already gets only the quick tools (arslan.QUICK_TOOLS) and learns nothing. Only a phone-made id with
    no messages yet: one that has messages ran with every tool and stays what it is. A retry is fine.
    `no_memory` is left as it is."""
    if not _QUICK_ID.fullmatch(conversation_id):
        raise HTTPException(400, "bad_request")
    if await db.scalar(select(ArslanMessage.id).where(ArslanMessage.conversation_id == conversation_id).limit(1)):
        raise HTTPException(409, "conversation_exists")
    row = await db.get(ConversationContext, conversation_id) or ConversationContext(id=conversation_id)
    row.kind, row.no_learning = "quick", True
    db.add(row)
    await db.commit()
    return {"conversation_id": conversation_id, "kind": "quick"}


class ConversationUpdate(BaseModel):
    kind: str


@router.post("/phone/conversations/{conversation_id}/update")
async def phone_update_conversation(conversation_id: str, body: ConversationUpdate,
                                    db: AsyncSession = Depends(get_session)):
    """Q1's `conversation.update`: a quick question becomes an ordinary chat, with every tool from its next
    turn. Refused while a turn runs (the Bridge answers `mac_busy`). Whether it then starts learning is the
    user's open question (card, #3); until they decide, `no_learning` stays as it is."""
    from server.services import run_registry, turn_journal
    if body.kind != "chat":
        raise HTTPException(400, "bad_request")
    row = await db.get(ConversationContext, conversation_id)
    if row is None:
        raise HTTPException(404, "not_found")
    if run_registry.active_for(conversation_id) or turn_journal.active(conversation_id):
        raise HTTPException(409, "mac_busy")
    row.kind = "chat"
    await db.commit()
    return {"conversation_id": conversation_id, "kind": "chat"}


@router.get("/phone/conversations/{conversation_id}/history")
async def phone_history(conversation_id: str, limit: int = Query(50, ge=1, le=200),
                        db: AsyncSession = Depends(get_session)):
    """`chat.history.result`: the latest `limit` messages, oldest first. Ids are the message ids
    the Mac's final `chat.event` uses too, so the phone can merge the two. Arslan's replies carry
    the files their run made."""
    rows = (await db.execute(
        select(ArslanMessage).where(ArslanMessage.conversation_id == conversation_id)
        .order_by(ArslanMessage.id.desc()).limit(limit))).scalars().all()
    messages = [
        {"id": str(m.id), "role": "user" if m.role == "user" else "assistant",
         "text": m.display_content or m.content, "ts": _iso(m.timestamp),
         "attachments": run_files(m.run_id), **({"run_id": m.run_id} if m.run_id else {}),
         # §5.7: who typed it — the phone ("from iPhone") or a Mac window.
         **({"source": "phone" if m.source == "phone" else "mac"} if m.role == "user" else {})}
        for m in reversed(rows)]
    # §5.7: one envelope holds it all; the oldest go first, and the phone is told.
    messages, truncated = phone_reads.fit_history(conversation_id, messages)
    return {"conversation_id": conversation_id, "messages": messages, **({"truncated": True} if truncated else {})}


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


@router.get("/phone/status")
async def phone_snapshot(db: AsyncSession = Depends(get_session)):
    """`status.snapshot` (§5.3) without what only the Bridge knows (its device name, the time):
    the island's state as the mascot, the jobs still running (as job_update frames, which the
    Bridge maps to job.event bodies like every other job update) and the cards waiting.
    Presence is "online" because this answered; the phone marks a Mac silent for 90 s offline.
    `high_risk_mac_only` stays false until that switch exists (§6.1)."""
    feed = desktop_status.island_feed()
    return {"presence": "online", "mascot": phone_mascot(feed, time.time()),
            "jobs": [job.frame() for job in background_jobs.active()],
            "waiting_approvals": feed["awaiting"], "high_risk_mac_only": False,
            "activity": await phone_reads.activity(db)}


@router.get("/phone/runs/{run_id}")
async def phone_run(run_id: int, db: AsyncSession = Depends(get_session)):
    """`run.result`: one turn or task, for quick review — its steps (a command's exit code and
    last lines, an edit's line diff, a new file's first lines), and the files it made."""
    detail = await phone_reads.run_detail(db, run_id)
    if detail is None:
        raise HTTPException(404, "run_not_found")
    return detail


class TaskStart(BaseModel):
    goal: str
    criteria: list[str] = []


@router.post("/phone/tasks")
async def phone_start_task(body: TaskStart):
    """`task.start`: a task handed over from the phone becomes its own conversation and a
    background job, exactly as if it had been started on the Mac."""
    try:
        return await phone_reads.start_task(body.goal, body.criteria)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/phone/tasks/{job_id}/stop")
async def phone_stop_task(job_id: str):
    if not phone_reads.stop_task(job_id):
        raise HTTPException(404, "task_not_running")
    return {"job_id": job_id, "stopped": True}


# ------------------------------------------------------------------ files from the phone (§5.7)

#: A saved name's length in characters, and in UTF-8 bytes (APFS allows 255; " (12)" must fit).
INBOX_NAME_MAX = 120
INBOX_NAME_BYTES = 200
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f:]")


def inbox_name(name: str) -> str:
    """One plain file name from whatever the phone called it: the last path component, no
    leading dots or spaces (never hidden, never "..") and no control characters or colons,
    capped with its extension kept; "file" when nothing is left."""
    last = re.split(r"[/\\]", name or "")[-1]
    clean = _UNSAFE_NAME.sub("_", last).strip().lstrip(".").strip()
    if not clean:
        return "file"
    stem, dot, ext = clean.rpartition(".")
    if not (dot and stem and len(ext) <= 16):
        stem, ext = clean, ""
    suffix = "." + ext if ext else ""
    cut = False
    while stem and (len(stem) + len(suffix) > INBOX_NAME_MAX or len((stem + suffix).encode()) > INBOX_NAME_BYTES):
        stem, cut = stem[:-1], True
    return ((stem.rstrip() if cut else stem) or "file") + suffix


def save_inbox_file(workspace: Path, name: str, data: bytes) -> Path:
    """<workspace>/Inbox/iPhone/<local date>/<name>; a name already there becomes "name (2).ext".
    Created exclusively, so two files of the same name never overwrite each other."""
    folder = workspace / "Inbox" / "iPhone" / datetime.now().astimezone().strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    folder = folder.resolve()
    if not folder.is_relative_to(workspace.resolve()):        # a symlink pointing out of the workspace
        raise OSError("inbox_outside_workspace")
    plain = Path(name)
    for n in range(1, 1000):
        target = folder / (name if n == 1 else f"{plain.stem} ({n}){plain.suffix}")
        try:
            with open(target, "xb") as handle:
                handle.write(data)
            return target
        except FileExistsError:
            continue
    raise OSError("inbox_name_taken")


class InboxFile(BaseModel):
    name: str
    mime_type: str = "application/octet-stream"
    data: str                      # standard base64 of the bytes
    sha256: str                    # hex of the bytes, as the phone's FileReference says


@router.post("/phone/inbox")
async def phone_inbox(body: InboxFile, db: AsyncSession = Depends(get_session)):
    """A file the phone sent (`file.offer` with its asset, already decrypted and checked by the
    Bridge): saved in the workspace so the agent can open the original with its own tools."""
    if len(body.data) > (PHONE_FILE_MAX + 2) // 3 * 4 + 4:
        raise HTTPException(413, "too_large")
    try:
        data = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "malformed") from None
    if len(data) > PHONE_FILE_MAX:
        raise HTTPException(413, "too_large")
    if hashlib.sha256(data).hexdigest() != body.sha256.strip().lower():
        raise HTTPException(422, "sha256_mismatch")
    workspace = await settings_service.workspace_dir(db)
    if workspace is None:                      # a chosen folder that is gone: never somewhere else
        raise HTTPException(503, "workspace_unavailable")
    try:
        path = await asyncio.to_thread(save_inbox_file, Path(workspace), inbox_name(body.name), data)
    except OSError:
        raise HTTPException(503, "inbox_unavailable") from None
    return {"path": str(path), "name": path.name, "mime_type": body.mime_type or "application/octet-stream",
            "size": len(data)}


# ------------------------------------------------------------------ live conversations (§5.7)

@router.get("/phone/live")
async def phone_live(limit: int = Query(20, ge=1, le=50), db: AsyncSession = Depends(get_session)):
    """The conversations the Bridge keeps a socket open on, so their answers, progress and
    shared cards reach the phone live: the newest `limit`, then every one with a running job.
    Never a temporary conversation: closing a socket on one clears its unsaved turn."""
    from server.api.conversations import list_conversations
    newest = [r.conversation_id for r in await list_conversations(db)]
    jobs = [job.conversation_id for job in background_jobs.active()]
    temporary = set((await db.execute(
        select(ConversationContext.id).where(ConversationContext.id.in_(newest + jobs),
                                             ConversationContext.temporary.is_(True)))).scalars())
    newest = [cid for cid in newest if cid not in temporary][:limit]
    return {"conversation_ids": list(dict.fromkeys(newest + [cid for cid in jobs if cid not in temporary]))}
