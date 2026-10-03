"""The judgment ledger, read-only (0.1.52 S2): what the judge model was asked and what
really happened. Activity shows it ("Judgments"); nothing here changes behaviour."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from server.auth import require_auth
from server.services import judgment

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/judgments")
async def list_judgments(limit: int = Query(50, ge=1, le=500), point: str | None = Query(None, max_length=40)):
    return {"points": {name: p.mode for name, p in judgment.REGISTRY.items()},
            "items": await judgment.recent(limit, point)}
