"""REST endpoints for long-term user_facts (Settings -> Memory)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from server.auth import require_auth
from server.orchestrator import memory
from server.schemas import FactIn, FactOut, FactUpdate

router = APIRouter(dependencies=[Depends(require_auth)])


def _to_out(row) -> FactOut:  # noqa: ANN001
    return FactOut(
        id=row.id,
        content=row.content,
        source=row.source,
        sensitive=row.sensitive,
        category=row.category,
    )


@router.get("/facts", response_model=list[FactOut])
async def list_facts() -> list[FactOut]:
    return [_to_out(r) for r in await memory.list_facts()]


@router.post("/facts", response_model=FactOut, status_code=201)
async def create_fact(body: FactIn) -> FactOut:
    try:
        row = await memory.add_manual_fact(body.content, body.sensitive)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(row)


@router.put("/facts/{fact_id}", response_model=FactOut)
async def edit_fact(fact_id: int, body: FactUpdate) -> FactOut:
    row = await memory.update_fact(fact_id, body.content, body.sensitive)
    if row is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return _to_out(row)


@router.delete("/facts/{fact_id}", status_code=204)
async def remove_fact(fact_id: int) -> Response:
    if not await memory.delete_fact(fact_id):
        raise HTTPException(status_code=404, detail="Fact not found")
    return Response(status_code=204)


@router.post("/facts/dedup")
async def dedup() -> dict:
    """Explicit, destructive exact-normalized dedup backfill. Only reachable here —
    never called on boot, on the write path, or from a timer."""
    from server.services import fact_dedup

    return {"deleted": await fact_dedup.dedup_facts()}


@router.post("/facts/classify")
async def classify() -> dict:
    """Kick off a fire-and-forget backfill of category for all facts where it's
    NULL. Single-flight (a second call while running is a no-op). Not wired into
    any write path yet."""
    from server.services import fact_classify

    fact_classify.schedule(fact_classify.classify_missing())
    return {"started": True, "status": fact_classify.classify_status()}
