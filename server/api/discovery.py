"""Read-only discovery layer: GitHub search + per-repo evaluate + curated candidate catalog.
Persists ONLY the curated catalog (discovery_candidates); ingestion stays P2b add_server."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.services import discovery_service, github_eval

router = APIRouter(prefix="/discovery", tags=["discovery"])


class EvaluateBody(BaseModel):
    ref: str


class SaveBody(BaseModel):
    snapshot: dict


@router.get("/search")
async def search(q: str = ""):
    try:
        return await github_eval.search_repos(q)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="GitHub request failed; try again later")


@router.post("/evaluate")
async def evaluate(body: EvaluateBody):
    parsed = github_eval.parse_repo_ref(body.ref)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid repo ref — use owner/repo or a github.com URL")
    try:
        return await discovery_service.evaluate_ref(*parsed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="GitHub request failed; try again later")


@router.post("/catalog")
async def save_candidate(body: SaveBody):
    try:
        return await discovery_service.save_candidate(body.snapshot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/catalog")
async def list_candidates():
    return await discovery_service.list_candidates()


@router.post("/catalog/{cand_id}/refresh")
async def refresh_candidate(cand_id: int):
    try:
        return await discovery_service.refresh_candidate(cand_id)
    except ValueError as exc:
        if "not found" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="GitHub request failed; try again later")


@router.delete("/catalog/{cand_id}")
async def delete_candidate(cand_id: int):
    await discovery_service.delete_candidate(cand_id)
    return {"ok": True}


class SkillGenerateBody(BaseModel):
    ref: str


class SkillCreateBody(BaseModel):
    full_name: str
    name: str
    category: str = "general"
    description: str = ""
    body: str


@router.post("/skill/generate")
async def generate_skill(body: SkillGenerateBody):
    parsed = github_eval.parse_repo_ref(body.ref)
    if parsed is None:
        raise HTTPException(status_code=400, detail="invalid repo ref — use owner/repo or a github.com URL")
    try:
        return await discovery_service.generate_skill_draft(*parsed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="GitHub request failed; try again later")


@router.post("/skill")
async def create_skill(body: SkillCreateBody):
    try:
        return await discovery_service.create_skill(body.full_name, body.name, body.category,
                                                    body.description, body.body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── P3: faithful SKILL.md importer (verbatim; license-gated; scripts → sandbox store) ────

class SkillScanBody(BaseModel):
    ref: str
    subpath: str = ""


class SkillImportBody(BaseModel):
    ref: str
    path: str


@router.post("/skills/scan")
async def scan_skills(body: SkillScanBody):
    from server.services import skill_import
    try:
        return await skill_import.scan_skills(body.ref, body.subpath)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="GitHub request failed; try again later")


@router.post("/skills/import")
async def import_skill(body: SkillImportBody):
    from server.services import skill_import
    try:
        return await skill_import.import_skill(body.ref, body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="GitHub request failed; try again later")
