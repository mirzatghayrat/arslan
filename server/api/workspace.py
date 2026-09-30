"""Arslan's working folder, for the task panel (0.1.48): where it is, what Arslan
recently put there, and open / show-in-Finder for one of those files.

Every path is confined to the workspace (resolved, symlinks followed) so this can
never be used to open or reveal anything else on the Mac."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from server.auth import require_auth
from server.db import session as db_session
from server.services import settings_service

router = APIRouter(dependencies=[Depends(require_auth)])
RECENT_LIMIT = 20
SCAN_LIMIT = 2000


class PathIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)     # relative to the workspace


async def _root() -> tuple[Path, bool]:
    async with db_session.AsyncSessionLocal() as db:
        root = await settings_service.workspace_dir(db)
        default = await settings_service.workspace_is_default(db)
    if root is None:
        raise HTTPException(409, detail={"code": "workspace_missing"})
    return root.resolve(), default


def inside(root: Path, relative: str) -> Path | None:
    try:
        target = (root / relative).resolve()
    except (OSError, RuntimeError):
        return None
    return target if target != root and target.is_relative_to(root) and target.exists() else None


def recent_files(root: Path, limit: int = RECENT_LIMIT) -> list[dict]:
    found, seen = [], 0
    for path in root.rglob("*"):
        seen += 1
        if seen > SCAN_LIMIT:
            break
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or not path.is_file():
            continue
        stat = path.stat()
        found.append({"path": str(rel), "name": path.name, "bytes": stat.st_size,
                      "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()})
    found.sort(key=lambda f: f["modified"], reverse=True)
    return found[:limit]


@router.get("/workspace")
async def get_workspace():
    root, default = await _root()
    return {"path": str(root), "is_default": default, "recent": await asyncio.to_thread(recent_files, root)}


async def _open(args: list[str]) -> None:
    if sys.platform != "darwin":
        raise HTTPException(501, detail={"code": "macos_only"})
    proc = await asyncio.create_subprocess_exec("/usr/bin/open", *args)
    await proc.wait()


@router.post("/workspace/open")
async def open_file(body: PathIn):
    root, _ = await _root()
    target = inside(root, body.path)
    if target is None:
        raise HTTPException(404, detail={"code": "not_in_workspace"})
    await _open([str(target)])
    return {"ok": True}


@router.post("/workspace/reveal")
async def reveal(body: PathIn | None = None):
    """Show a file in Finder, or the folder itself when no path is given."""
    root, _ = await _root()
    if body is None:
        await _open([str(root)])
        return {"ok": True}
    target = inside(root, body.path)
    if target is None:
        raise HTTPException(404, detail={"code": "not_in_workspace"})
    await _open(["-R", str(target)])
    return {"ok": True}
