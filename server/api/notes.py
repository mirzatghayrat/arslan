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


@router.post("/brain/notes/{note_id}/suggest")
async def suggest(note_id: int) -> dict:
    from server.db import session as db_session
    from sqlalchemy import text as sa_text
    async with db_session.AsyncSessionLocal() as db:
        titles = [r[0] for r in (await db.execute(sa_text("SELECT title FROM notes"))).all()]
        labels = [r[0] for r in (await db.execute(sa_text("SELECT label FROM learnings WHERE label IS NOT NULL"))).all()]
        facts = [r[0] for r in (await db.execute(sa_text("SELECT COALESCE(label, content) FROM user_facts"))).all()]
        srcs = [r[0] for r in (await db.execute(sa_text("SELECT DISTINCT source FROM knowledge_chunks"))).all()]
    return await note_service.suggest_links(note_id, candidate_labels=titles + labels + facts + srcs)


@router.post("/brain/notes/generate")
async def generate(request: Request) -> dict:
    body = await request.json()
    made = await note_service.generate_notes(body.get("topic", ""), int(body.get("n", 4)))
    return {"created": made}
