"""REST endpoints for long-term user_facts (Settings -> Memory)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from server.auth import require_auth
from server.orchestrator import memory
from server.schemas import FactIn, FactOut, FactUpdate
from arslan.companion.memory import MemoryError

router = APIRouter(dependencies=[Depends(require_auth)])


def _to_out(row) -> FactOut:  # noqa: ANN001
    return FactOut(
        id=row.id,
        entry_id=getattr(row, "entry_id", None),
        version=getattr(row, "version", None),
        status=getattr(row, "status", None),
        content=row.content,
        source=row.source,
        sensitive=row.sensitive,
        category=row.category,
        label=row.label,
        valid_from=row.valid_from,
        superseded_by=row.superseded_by,
        provenance=row.provenance,
    )


@router.get("/facts", response_model=list[FactOut])
async def list_facts(include_superseded: bool = False) -> list[FactOut]:
    return [_to_out(r) for r in await memory.list_facts(include_superseded=include_superseded)]


@router.post("/facts", response_model=FactOut, status_code=201)
async def create_fact(body: FactIn) -> FactOut:
    try:
        row = await memory.add_manual_fact(body.content, body.sensitive)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(row)


@router.put("/facts/{fact_id}", response_model=FactOut)
async def edit_fact(fact_id: int, body: FactUpdate) -> FactOut:
    try:
        row = await memory.update_fact(fact_id, body.content, body.sensitive,
                                       expected_version=body.expected_version)
    except MemoryError as exc:
        raise HTTPException(status_code=428 if exc.code == "memory_version_required" else
                            409 if exc.code == "memory_version_conflict" else 422, detail=exc.code) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return _to_out(row)


@router.delete("/facts/{fact_id}", status_code=204)
async def remove_fact(fact_id: int, expected_version: int | None = None) -> Response:
    try:
        removed = await memory.delete_fact(fact_id, expected_version=expected_version)
    except MemoryError as exc:
        raise HTTPException(status_code=428 if exc.code == "memory_version_required" else
                            409 if exc.code == "memory_version_conflict" else 422, detail=exc.code) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Fact not found")
    return Response(status_code=204)


@router.post("/facts/dedup")
async def dedup() -> dict:
    """Kept for the API's shape. Memory v2 never bulk-deletes history (it proposes conflicts), so nothing is
    deleted. 0.1.63 C2a-2 removed the v1 backfill. DELETE-BY: v0.1.64, with the v1 tables (C7's third step)."""
    return {"deleted": 0}


@router.post("/facts/classify")
async def classify() -> dict:
    """Kept for the API's shape. Background classification was v1-only (it had no cloud-memory consent), so it
    never starts. 0.1.63 C2a-2 removed the classifier. DELETE-BY: v0.1.64, with the v1 tables (C7's third step)."""
    return {"started": False, "reason": "legacy_classification_disabled",
            "status": {"running": False, "done": 0, "total": 0, "error": None}}
