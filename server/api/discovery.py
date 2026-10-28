"""Importing SKILL.md files from a GitHub link (the import panel on the Capabilities page).

v0.1.64 CAP1a removed the rest of the discovery centre (search, evaluate, the saved catalog and
skill drafts); finding a capability now happens in the conversation (find_capability)."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth

router = APIRouter(prefix="/discovery", tags=["discovery"], dependencies=[Depends(require_auth)])


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
