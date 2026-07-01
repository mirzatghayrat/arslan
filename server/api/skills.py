"""Skill forge endpoints: author a skill draft, then human-confirm to register
it as a real, live, equippable library skill."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from server.auth import require_auth
from server.db.models import SkillCandidate
from server.schemas import SkillCandidateOut, SkillEvaluateIn, SkillForgeIn
from server.services import skill_forge

router = APIRouter(dependencies=[Depends(require_auth)])


def _to_out(c: SkillCandidate) -> SkillCandidateOut:
    return SkillCandidateOut(
        id=c.id, key=c.key, name=c.name, category=c.category,
        description=c.description, status=c.status, source=c.source,
        created_at=c.created_at.isoformat() if c.created_at else None,
        promoted_at=c.promoted_at.isoformat() if c.promoted_at else None,
    )


@router.post("/skills/forge", response_model=SkillCandidateOut)
async def forge_skill(body: SkillForgeIn) -> SkillCandidateOut:
    try:
        cand = await skill_forge.create_candidate(
            key=body.key, name=body.name, category=body.category,
            description=body.description, body=body.body, source=body.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(cand)


@router.get("/skills/candidates", response_model=list[SkillCandidateOut])
async def list_skill_candidates(status: str | None = None) -> list[SkillCandidateOut]:
    cands = await skill_forge.list_candidates(status)
    return [_to_out(c) for c in cands]


@router.post("/skills/candidates/{candidate_id}/evaluate")
async def evaluate_skill_candidate(candidate_id: int, body: SkillEvaluateIn) -> dict:
    """Real-data eval gate: observe -> evaluate -> proposed. Informs the human confirm."""
    return await skill_forge.evaluate_candidate(
        candidate_id, body.target_spawn_id, min_samples=body.min_samples,
    )


@router.post("/skills/candidates/{candidate_id}/promote")
async def promote_skill_candidate(candidate_id: int) -> dict:
    result = await skill_forge.promote_candidate(candidate_id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "cannot promote"))
    return result


@router.post("/skills/candidates/{candidate_id}/reject")
async def reject_skill_candidate(candidate_id: int) -> dict:
    return await skill_forge.reject_candidate(candidate_id)
