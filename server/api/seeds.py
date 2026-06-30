"""Persona-seed library browse API — the 249 seed identities a spawn can be composed from."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from server.auth import require_auth
from server.services import persona_seed_service

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/seeds")
async def list_seeds(
    query: str | None = Query(default=None),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Browse/search the persona-seed library for the Spawn Studio panel.
    Returns {seeds: [{slug, name, division, summary}], total}."""
    seeds = await persona_seed_service.list_seeds(query, limit=limit, offset=offset)
    total = await persona_seed_service.count()
    return {"seeds": seeds, "total": total}
