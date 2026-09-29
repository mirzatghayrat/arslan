"""0.1.44: list former experts and turn one into a skill (Capabilities page)."""
from fastapi import APIRouter, Depends, HTTPException

from server.auth import require_auth
from server.services import expert_conversion

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/experts/legacy")
async def legacy_experts():
    return {"experts": await expert_conversion.list_experts()}


@router.post("/experts/{spawn_id}/to-skill")
async def to_skill(spawn_id: int):
    result = await expert_conversion.convert(spawn_id)
    if not result.get("ok"):
        raise HTTPException(404 if result.get("code") == "expert_not_found" else 422,
                            detail={"code": result.get("code")})
    return result
