"""Read-only discovery layer: GitHub search + per-repo evaluate + curated candidate catalog.
Persists ONLY the curated catalog (discovery_candidates); ingestion stays P2b add_server."""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
from server.services import discovery_service, github_eval

router = APIRouter(prefix="/discovery", tags=["discovery"], dependencies=[Depends(require_auth)])
logger = logging.getLogger(__name__)


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
    # 0.1.61 §C4: the sha256 of the license text the person read and accepted for use on this Mac.
    # It reaches the importer from here, a person's own request, and from nowhere a model can write to.
    license_ok: str | None = None


@router.post("/skills/scan")
async def scan_skills(body: SkillScanBody):
    from server.services import skill_import
    try:
        return await skill_import.scan_skills(body.ref, body.subpath)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="GitHub request failed; try again later")


def _github_did_not_answer(exc: BaseException) -> HTTPException:
    """502, and why in neutral words: the status GitHub answered, or the importer's own words for a
    stalled download (nobody is blamed in them), or what kind of failure it was. Never httpx's text,
    which can carry an address and a link."""
    if isinstance(exc, httpx.HTTPStatusError):
        why = f"it answered {exc.response.status_code}"
    elif isinstance(exc, httpx.TimeoutException):
        why = str(exc)[:200] or "the request timed out"
    elif isinstance(exc, TimeoutError):               # a transport's own, which is an OSError but not the disk's
        why = "the request timed out"
    elif isinstance(exc, httpx.NetworkError):
        why = "the connection failed"
    else:
        why = "the request failed"
    return HTTPException(status_code=502, detail=f"GitHub did not answer: {why}")


@router.post("/skills/import")
async def import_skill(body: SkillImportBody):
    """Import one skill the person named (0.1.61 §C2, §C4). A license Arslan does not recognise
    answers 409 with its text; the person reads it and imports again with license_ok. Every answer the
    importer can give is mapped here: 409 the license step, 400 a refusal, 502 GitHub did not answer,
    500 with the code `disk` when the folder could not be written (an OSError may be a full disk, a
    folder it may not write or a failing drive, so not 507, which says only the first)."""
    from server.services import skill_import, skill_ledger
    try:
        out = await skill_import.import_skill(body.ref, body.path, license_ok=body.license_ok)
    except skill_import.LicenseStepNeeded as step:       # first: it is a ValueError
        # The text is the repository's, the attacker's to write: it goes out as a JSON string and into
        # no HTML, log line or message here. The reader shows it with its control and bidi characters
        # visible (Task 12). Always whole: `text_omitted` is the scan's, never the step's.
        raise HTTPException(status_code=409, detail={
            "code": "license_step", "key": step.key, "name": step.name,
            "license": step.license.view(with_text=True)}) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except (httpx.HTTPError, TimeoutError) as exc:       # TimeoutError before OSError, which it is
        raise _github_did_not_answer(exc) from None
    except OSError as exc:
        logger.warning("skill import: the skill's folder could not be written (errno %s)", exc.errno)
        raise HTTPException(status_code=500, detail={
            "code": "disk",
            "message": f"could not write the skill's folder: {exc.strerror or type(exc).__name__}"}) from None
    await skill_ledger.record(target=f"skill:{out['key']}", detail=f"{body.ref} {body.path}", allowed=True,
                              extra={"local_only": out["local_only"], "update": out["update"],
                                     "commit": out["commit"][:12]})
    return out
