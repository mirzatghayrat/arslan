"""What Arslan can do, as switches (0.1.55 §14). See services/capability_list."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
from server.services import capability_list

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/capabilities")
async def list_capabilities() -> list[dict]:
    return await capability_list.capabilities()


class Switch(BaseModel):
    on: bool


@router.put("/capabilities/{key:path}")
async def switch_capability(key: str, body: Switch) -> dict:
    try:
        await capability_list.switch(key, body.on)
    except capability_list.NotSwitchable as exc:
        raise HTTPException(status_code=409, detail={"code": "not_switchable"}) from exc
    row = next((r for r in await capability_list.capabilities() if r["key"] == key), None)
    return row or {"key": key}


@router.delete("/capabilities/{key:path}")
async def remove_capability(key: str) -> dict:
    """v0.1.64 CAP3a-1: delete what the user installed, Arslan wrote or the user added by hand; refuse the rest
    (a built-in is only switched), whatever the page shows."""
    try:
        await capability_list.remove(key)
    except capability_list.NotFound as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found"}) from exc
    except capability_list.NotRemovable as exc:
        raise HTTPException(status_code=409, detail={"code": "not_removable"}) from exc
    return {"ok": True}


# ── 0.1.57 §7: what Arslan installed — its dossier, folders, updates, removal ──

def _dossier_error(exc) -> HTTPException:
    status = 404 if exc.code.endswith("not_found") else 409
    return HTTPException(status_code=status, detail={"code": exc.code})


@router.get("/capability-sources")
async def capability_sources() -> list[dict]:
    from server.services import capability_dossier
    return await capability_dossier.sources()


@router.get("/capability-sources/{source_id}")
async def capability_source(source_id: str) -> dict:
    from server.services import capability_dossier
    try:
        return capability_dossier.view(await capability_dossier.source(source_id))
    except capability_dossier.DossierError as exc:
        raise _dossier_error(exc) from exc


class FoldersIn(BaseModel):
    folders: list[str]


@router.put("/capability-sources/{source_id}/folders")
async def set_folders(source_id: str, body: FoldersIn) -> dict:
    from server.services import capability_dossier
    try:
        return await capability_dossier.set_folders(source_id, body.folders[:3])
    except capability_dossier.DossierError as exc:
        raise _dossier_error(exc) from exc


@router.delete("/capability-sources/{source_id}")
async def remove_source(source_id: str) -> dict:
    """Remove: switched off, its folder to the Trash (never deleted outright)."""
    from server.services import capability_dossier
    try:
        await capability_dossier.remove(source_id)
    except capability_dossier.DossierError as exc:
        raise _dossier_error(exc) from exc
    return {"ok": True}


@router.get("/capability-sources/{source_id}/update")
async def check_update(source_id: str) -> dict:
    from server.services import capability_dossier
    try:
        return await capability_dossier.check_update(source_id)
    except capability_dossier.DossierError as exc:
        raise _dossier_error(exc) from exc


@router.post("/capability-sources/{source_id}/update")
async def apply_update(source_id: str) -> dict:
    from server.services import capability_dossier
    try:
        result = await capability_dossier.update(source_id)
    except capability_dossier.DossierError as exc:
        raise _dossier_error(exc) from exc
    return {k: v for k, v in result.items() if k in ("state", "source_id", "stage", "code", "detail", "tools")}
