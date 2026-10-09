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


@router.get("/capability-search")
async def search_capabilities(q: str = "", kind: str | None = None) -> dict:
    """0.1.57 §2/§9: the Discover box — what you want done, across the official MCP Registry,
    GitHub and reviewed skill libraries. Read-only; nothing here installs."""
    from server.services import capability_search
    from server.services import capability_dossier
    words = await capability_search.words_for(q)
    kinds = {kind} if kind in ("mcp", "skill", "project") else None
    result = await capability_search.search(q, words=words, kinds=kinds)
    # Kept server-side so "加进能力库" on a dossier names one of THESE candidates.
    capability_search.remember(capability_dossier.PAGE, result)
    return result


# ── 0.1.57 §4 §7 §8: found for later, dossiers, install from the page, projects ──

def _dossier_error(exc) -> HTTPException:
    status = 404 if exc.code.endswith("not_found") or exc.code == "unknown_candidate" else 409
    return HTTPException(status_code=status, detail={"code": exc.code})


@router.get("/capability-finds")
async def capability_finds() -> list[dict]:
    from server.services import capability_dossier
    return await capability_dossier.finds()


@router.post("/capability-finds/{find_id}/dismiss")
async def dismiss_find(find_id: str) -> dict:
    from server.services import capability_dossier
    try:
        await capability_dossier.dismiss(find_id)
    except capability_dossier.DossierError as exc:
        raise _dossier_error(exc) from exc
    return {"ok": True}


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


class CandidateRef(BaseModel):
    candidate_id: str


@router.post("/capability-candidates/check")
async def check_candidate(body: CandidateRef) -> dict:
    from server.services import capability_dossier
    try:
        return await capability_dossier.check(body.candidate_id)
    except capability_dossier.DossierError as exc:
        raise _dossier_error(exc) from exc


class InstallIn(BaseModel):
    candidate_id: str
    folders: list[str] = []
    keys: dict[str, str] = {}


@router.post("/capability-candidates/install")
async def install_candidate(body: InstallIn) -> dict:
    """"加进能力库": the user names this candidate on its dossier — install, scan, test, switch on."""
    from server.services import capability_dossier
    try:
        result = await capability_dossier.install(body.candidate_id, folders=body.folders[:3], keys=body.keys)
    except capability_dossier.DossierError as exc:
        raise _dossier_error(exc) from exc
    return {k: v for k, v in result.items() if k in ("state", "source_id", "stage", "code", "detail", "tools", "skill")}


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


class MaterialIn(BaseModel):
    candidate_id: str


@router.post("/projects/{project_id}/capability-material")
async def as_material(project_id: str, body: MaterialIn) -> dict:
    from server.services import capability_dossier
    try:
        return await capability_dossier.as_material(project_id, body.candidate_id)
    except capability_dossier.DossierError as exc:
        raise _dossier_error(exc) from exc
