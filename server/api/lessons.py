"""Learned practices in Brain (0.1.52 S5): list them, accept or undo, pin, delete.
Only the user changes a lesson's status here; Arslan's own capture is lessons.py."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select

from server.auth import require_auth
from server.db import session as db_session
from server.db.models import Judgment, Lesson
from server.services import lessons

router = APIRouter(dependencies=[Depends(require_auth)])


class LessonStatus(BaseModel):
    status: Literal["active", "archived"]
    # F4 (#460 review): the `updated_at` of the row Memory's sheet showed. A row that changed since (a
    # merge counted it up or rewrote it, or a deleted id was reused by a new lesson) is refused, not
    # switched on. Switching on requires it, so no way in skips the check (#466 review); retiring does
    # not (the chat's Undo).
    expected_updated_at: str | None = None


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


async def _change(lesson_id: int, *, edit=None, expected_updated_at: str | None = None, **values) -> dict:
    from datetime import datetime
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Lesson, lesson_id)
        if row is None:
            raise HTTPException(404, "lesson_not_found")
        if expected_updated_at is not None and lessons.present(row)["updated_at"] != expected_updated_at:
            raise HTTPException(409, "lesson_version_conflict")
        for key, value in values.items():
            setattr(row, key, value)
        if edit is not None:
            edit(row)
        row.updated_at = datetime.utcnow()
        await db.commit()
        return lessons.present(row)


@router.post("/lessons/{lesson_id}/status")
async def lesson_status(lesson_id: int, body: LessonStatus):
    """Switch on one that is not in effect, or restore (active); undo or retire (archived, restorable).
    INB1: switching one on drops why it was not in effect (the reason, the rival, the failure count);
    Memory shows the full text and that reason before the user switches it on, and sends the
    `updated_at` it showed (F4)."""
    if body.status == "active" and body.expected_updated_at is None:
        raise HTTPException(422, "lesson_version_required")
    return await _change(lesson_id, status=body.status, edit=lessons.switched_on if body.status == "active" else None,
                         expected_updated_at=body.expected_updated_at)


@router.post("/lessons/{lesson_id}/pin")
async def lesson_pin(lesson_id: int, body: LessonPin):
    return await _change(lesson_id, pinned=body.pinned)


class LessonRule(BaseModel):
    conversation_id: str
    action: Literal["add", "skip", "remove"]


@router.post("/lessons/{lesson_id}/rule")
async def lesson_rule(lesson_id: int, body: LessonRule):
    """L11-2: the "make this a rule for this folder?" card. `add` appends the lesson's words to the conversation's
    folder's rules file (only a lesson the card offered, once); `skip` records "not now"; `remove` takes the line the
    card added back out. The user's click, never the model's tools (HR keeps model writes to these files)."""
    from server.services import folder_rules
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Lesson, lesson_id)
        if row is None:
            raise HTTPException(404, "lesson_not_found")
        evidence = dict(row.evidence or {})
        state = evidence.get(lessons.RULE_OFFER)
        needed = {"add": "offered", "skip": "offered", "remove": "added"}[body.action]
        if state != needed:
            raise HTTPException(409, "rule_not_offered" if body.action != "remove" else "rule_not_added")
        out: dict = {}
        if body.action == "skip":
            evidence[lessons.RULE_OFFER] = "skipped"
        elif body.action == "add":
            folder = await folder_rules.conversation_folder(db, body.conversation_id)
            if folder is None or folder == folder_rules._home():
                raise HTTPException(409, "no_folder")
            line = lessons.render(row)
            try:
                path = await folder_rules.add_rule(db, folder, line)
            except (folder_rules.RuleRefused, OSError):
                raise HTTPException(409, "rules_file_refused") from None
            evidence.update({lessons.RULE_OFFER: "added", "rule_file": str(path), "rule_line": line})
            out["file"] = folder_rules._shown(path, folder_rules._home())
        else:
            from pathlib import Path
            path = Path(evidence.get("rule_file") or "")
            try:
                await folder_rules.remove_rule(db, path, evidence.get("rule_line") or "")
            except (folder_rules.RuleRefused, OSError):
                raise HTTPException(409, "rules_file_refused") from None
            evidence[lessons.RULE_OFFER] = "removed"
            out["file"] = folder_rules._shown(path, folder_rules._home())
        row.evidence = evidence
        await db.commit()
    return {"state": evidence[lessons.RULE_OFFER], **out}


@router.get("/conversations/{conversation_id}/folder-rules")
async def conversation_folder_rules(conversation_id: str):
    """K10-1 / L11-0: the rules files this conversation follows, for Overview (each with its text), and whether the
    switch is on. Read only; the same exact-name, no-link reads as the turn's block."""
    from server.services import folder_rules
    return await folder_rules.listing(conversation_id)


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(lesson_id: int):
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Lesson, lesson_id)
        if row is None:
            raise HTTPException(404, "lesson_not_found")
        await db.delete(row)
        # JUDGE1: the judgments ledger's rows keyed to it (merge, conflict, applied) go too. The candidate side of a
        # question is never kept as text (judgment's `redact`), so no row elsewhere still holds this lesson's words.
        await db.execute(delete(Judgment).where(Judgment.ref == f"lesson:{lesson_id}"))
        await db.commit()
    return {"id": lesson_id, "deleted": True}
