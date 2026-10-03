"""Learned practices in Brain (0.1.52 S5): list them, accept or undo, pin, delete.
Only the user changes a lesson's status here; Arslan's own capture is lessons.py."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from server.auth import require_auth
from server.db import session as db_session
from server.db.models import Lesson
from server.services import lessons

router = APIRouter(dependencies=[Depends(require_auth)])


class LessonStatus(BaseModel):
    status: Literal["active", "archived"]


class LessonPin(BaseModel):
    pinned: bool


@router.get("/lessons")
async def list_lessons(status: Literal["active", "proposed", "stale", "archived"] | None = Query(None),
                       limit: int = Query(200, ge=1, le=500)):
    async with db_session.AsyncSessionLocal() as db:
        q = select(Lesson).order_by(Lesson.updated_at.desc(), Lesson.id.desc()).limit(limit)
        if status:
            q = q.where(Lesson.status == status)
        return [lessons.present(row) for row in (await db.scalars(q)).all()]


async def _change(lesson_id: int, **values) -> dict:
    from datetime import datetime
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Lesson, lesson_id)
        if row is None:
            raise HTTPException(404, "lesson_not_found")
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = datetime.utcnow()
        await db.commit()
        return lessons.present(row)


@router.post("/lessons/{lesson_id}/status")
async def lesson_status(lesson_id: int, body: LessonStatus):
    """Accept a proposal or restore (active); undo or retire (archived, restorable)."""
    return await _change(lesson_id, status=body.status)


@router.post("/lessons/{lesson_id}/pin")
async def lesson_pin(lesson_id: int, body: LessonPin):
    return await _change(lesson_id, pinned=body.pinned)


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(lesson_id: int):
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Lesson, lesson_id)
        if row is None:
            raise HTTPException(404, "lesson_not_found")
        await db.delete(row)
        await db.commit()
    return {"id": lesson_id, "deleted": True}
