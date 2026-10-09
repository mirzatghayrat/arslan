"""Files in Arslan's window (0.1.58 §2–§3): browse a folder, read a file, stat the paths a
reply mentions, open or reveal one, and the files a conversation produced.

Reading is limited to file_reader.roots(); revealing in Finder works anywhere (it does not
read the file). File bytes leave as an attachment with nosniff: the page fetches them and
renders them itself (HTML only in a sandbox="" iframe), so nothing a file contains can run
as a page of Arslan's own origin.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.services import file_reader
from server.services.file_reader import NotReadable

router = APIRouter(dependencies=[Depends(require_auth)])

_STATUS = {"outside": 403, "hidden": 403, "missing": 404, "too_big": 413, "invalid_path": 422}


def _err(exc: NotReadable) -> HTTPException:
    return HTTPException(_STATUS.get(exc.code, 422), detail={"code": exc.code})


def _attachment(data: bytes, name: str, media_type: str = "application/octet-stream") -> Response:
    return Response(content=data, media_type=media_type, headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


class PathIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=4096)


class PathsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(max_length=file_reader.STAT_LIMIT)


@router.get("/files/list")
async def list_folder(path: str = Query(min_length=1, max_length=4096), offset: int = Query(0, ge=0)) -> dict:
    try:
        return await asyncio.to_thread(file_reader.listing, path, await file_reader.roots(), offset=offset)
    except NotReadable as exc:
        raise _err(exc) from exc


@router.get("/files/read")
async def read(path: str = Query(min_length=1, max_length=4096)) -> Response:
    try:
        found, data = await asyncio.to_thread(file_reader.read_bytes, path, await file_reader.roots())
    except NotReadable as exc:
        raise _err(exc) from exc
    return _attachment(data, found.name)


@router.post("/files/stat")
async def stat(body: PathsIn) -> dict:
    return {"items": await asyncio.to_thread(file_reader.stat, body.paths, await file_reader.roots())}


@router.get("/files/table")
async def table(path: str = Query(min_length=1, max_length=4096)) -> dict:
    try:
        found, data = await asyncio.to_thread(file_reader.read_bytes, path, await file_reader.roots())
        return await asyncio.to_thread(file_reader.table, found.name, data)
    except NotReadable as exc:
        raise _err(exc) from exc


@router.get("/files/html")
async def as_html(path: str = Query(min_length=1, max_length=4096)) -> dict:
    """A document (docx, rtf…) as HTML text — the page shows it in a sandbox="" iframe."""
    if sys.platform != "darwin":
        raise HTTPException(501, detail={"code": "macos_only"})
    try:
        found, _ = await asyncio.to_thread(file_reader.read_bytes, path, await file_reader.roots())
        return {"html": await file_reader.as_html(found)}
    except NotReadable as exc:
        raise _err(exc) from exc


@router.get("/files/pdf-page")
async def pdf_page(path: str = Query(min_length=1, max_length=4096), page: int = Query(0, ge=0)) -> Response:
    try:
        found, data = await asyncio.to_thread(file_reader.read_bytes, path, await file_reader.roots())
        png, count = await asyncio.to_thread(file_reader.pdf_page, data, page)
    except NotReadable as exc:
        raise _err(exc) from exc
    response = _attachment(png, f"{found.stem}-{page + 1}.png", "image/png")
    response.headers["X-Page-Count"] = str(count)
    return response


async def _open(args: list[str]) -> None:
    if sys.platform != "darwin":
        raise HTTPException(501, detail={"code": "macos_only"})
    proc = await asyncio.create_subprocess_exec("/usr/bin/open", *args)
    await proc.wait()


@router.post("/files/open")
async def open_file(body: PathIn) -> dict:
    """Open in the default app — only a readable file (the same boundary as reading)."""
    try:
        found, _ = await asyncio.to_thread(file_reader.resolve, body.path, await file_reader.roots())
    except NotReadable as exc:
        raise _err(exc) from exc
    await _open([str(found)])
    return {"ok": True}


@router.post("/files/reveal")
async def reveal(body: PathIn) -> dict:
    """Show in Finder — anywhere: Finder shows it, Arslan does not read it."""
    p = Path(body.path.strip()).expanduser()
    if not p.is_absolute() or not p.exists():
        raise HTTPException(404, detail={"code": "missing"})
    await _open(["-R", str(p)])
    return {"ok": True}


@router.get("/files/home")
async def home(conversation_id: str | None = Query(None, max_length=100), db: AsyncSession = Depends(get_session)) -> dict:
    """Where the 文件 tab starts for a conversation: its project's folder, else the workspace."""
    from server.db.companion_models import ConversationContext, Project
    from server.services import settings_service
    folder = None
    project = None
    if conversation_id:
        ctx = await db.get(ConversationContext, conversation_id)
        if ctx is not None and ctx.project_id:
            row = await db.get(Project, ctx.project_id)
            if row is not None:
                project = {"id": row.id, "name": row.name}
                raw = (row.workspace_ref or "").strip()
                if raw and Path(raw).expanduser().is_dir():
                    folder = file_reader._home(Path(raw).expanduser().resolve())
    if folder is None:
        ws = await settings_service.workspace_dir(db)
        folder = file_reader._home(ws.resolve()) if ws else None
    return {"path": folder, "project": project}


@router.get("/conversations/{conversation_id}/files")
async def conversation_files(conversation_id: str, db: AsyncSession = Depends(get_session)) -> dict:
    """The files this conversation's runs produced, newest first, one per path (its last version)."""
    from server.db.models import Run
    from server.services import artifact_store
    runs = (await db.execute(select(Run.id, Run.created_at).where(Run.conversation_id == conversation_id)
                             .order_by(Run.id.desc()).limit(200))).all()
    seen: set[str] = set()
    out = []
    for run_id, created in runs:
        for item in await asyncio.to_thread(artifact_store.list_artifacts, run_id):
            key = item.get("logical_key") or item.get("filename")
            if key in seen:
                continue
            seen.add(key)
            out.append({**item, "created_at": created.isoformat() if created else None})
    return {"files": out[:200]}
