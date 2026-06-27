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
