"""Hand-written Second-Brain notes: CRUD + AI helpers (suggest/generate added later)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from server.auth import require_auth
from server.services import note_service

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/brain/notes")
async def list_notes() -> list[dict]:
    return await note_service.list_notes()


@router.get("/brain/notes/{note_id}")
async def get_note(note_id: int) -> dict:
    n = await note_service.get(note_id)
    if n is None:
        raise HTTPException(404)
    n["backlinks"] = await note_service.backlinks(n["title"])
    return n


@router.post("/brain/notes")
async def create_note(request: Request) -> dict:
    body = await request.json()
    n = await note_service.create(body.get("title", ""), body.get("content", ""), body.get("tags") or [])
    return note_service._dump(n)


@router.patch("/brain/notes/{note_id}")
async def update_note(note_id: int, request: Request) -> dict:
    body = await request.json()
    n = await note_service.update(note_id, title=body.get("title"), content=body.get("content"),
                                  tags=body.get("tags"))
    if n is None:
        raise HTTPException(404)
    return n


@router.delete("/brain/notes/{note_id}")
async def delete_note(note_id: int) -> dict:
    return {"deleted": await note_service.delete(note_id)}
