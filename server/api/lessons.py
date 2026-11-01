"""Learned practices in Brain (0.1.52 S5): list them, accept or undo, pin, delete.
Only the user changes a lesson's status here; Arslan's own capture is lessons.py."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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
    """L11-2: the "make this a rule for this folder?" card. The user's click, never the model's tools (HR keeps model
    writes to these files).
    - `add` writes exactly the line the card showed into exactly the file it named (the offer's record, #603 F2). 409
      `conversation_changed` from another conversation; `folder_changed` when the conversation's folder no longer
      leads to that file; `lesson_changed` when the lesson changed since the card was offered (a later correction or
      a detour folded in): the offer then goes, so a later correction can bring a new card. Once.
    - `skip` records "not now"; `remove` takes the card's line back out, with `in_file` false when it had changed in
      the file (it is then left there).
    - 409 `rules_file_refused` / `rules_file_full` when the file is a link, not writable, or would pass what a turn
      reads."""
    from datetime import datetime
    from pathlib import Path
    from server.services import folder_rules
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Lesson, lesson_id)
        if row is None:
            raise HTTPException(404, "lesson_not_found")
        evidence = dict(row.evidence or {})
        state, record = evidence.get(lessons.RULE_OFFER), evidence.get(lessons.RULE_RECORD) or {}
        needed = {"add": "offered", "skip": "offered", "remove": "added"}[body.action]
        if state != needed or not record:
            raise HTTPException(409, "rule_not_offered" if body.action != "remove" else "rule_not_added")
        path = Path(record["path"])
        update: dict = {}
        if body.action == "skip":
            update = {lessons.RULE_OFFER: "skipped"}
        elif body.action == "add":
            if body.conversation_id != record.get("conversation_id"):
                raise HTTPException(409, "conversation_changed")
            if row.updated_at.isoformat() != record.get("updated_at"):
                evidence.pop(lessons.RULE_OFFER, None)
                evidence.pop(lessons.RULE_RECORD, None)
                row.evidence = evidence
                await db.commit()
                raise HTTPException(409, "lesson_changed")
            folder = await folder_rules.chosen_folder(db, body.conversation_id)
            if folder is None or folder == folder_rules._home() or folder_rules.target(folder) != path:
                raise HTTPException(409, "folder_changed")
            try:
                await folder_rules.add_rule(db, path, record["line"], lesson_id)
            except folder_rules.RuleRefused as exc:
                raise HTTPException(409, "rules_file_full" if exc.code == "full" else "rules_file_refused") from None
            update = {lessons.RULE_OFFER: "added", "rule_added_at": datetime.utcnow().isoformat()}
        else:
            try:
                in_file = await folder_rules.remove_rule(db, path, lesson_id, record.get("line"))
            except folder_rules.RuleRefused:
                raise HTTPException(409, "rules_file_refused") from None
            update = {lessons.RULE_OFFER: "removed"}
        # The file work may have taken a moment: what a capture wrote meanwhile stays (#603 F7).
        await db.refresh(row)
        row.evidence = {**dict(row.evidence or {}), **update}
        await db.commit()
    out = {"state": update[lessons.RULE_OFFER], "file": folder_rules._shown(path, folder_rules._home())}
    # #621 re-check, R2: as Overview's Remove, say when the line was no longer in the file as Add wrote it.
    return {**out, "in_file": in_file is not False} if body.action == "remove" else out


@router.get("/conversations/{conversation_id}/folder-rules")
async def conversation_folder_rules(conversation_id: str):
    """K10-1 / L11-0: the rules files this conversation follows, for Overview (each with its text), and whether the
    switch is on. Read only; the same exact-name, no-link reads as the turn's block."""
    from server.services import folder_rules
    return await folder_rules.listing(conversation_id)


class FolderRuleRemove(BaseModel):
    file: str = Field(max_length=4096)
    lesson_id: int
    line: str = Field(max_length=lessons.RULE_LINE_MAX)


@router.post("/conversations/{conversation_id}/folder-rules/remove")
async def conversation_folder_rule_remove(conversation_id: str, body: FolderRuleRemove):
    """L11-3a: Overview's Remove, from the rules record, so it works after the lesson was deleted in Memory. `file`
    is a name Overview's listing showed for this conversation (409 `rules_file_not_listed` otherwise); the line must
    be one the card added there under that lesson (409 `rule_not_added`). A lesson still there is marked removed.
    `in_file` is false when the line was no longer in the file as Add wrote it (edited, or the file now CRLF): it is
    dropped from the record and the file is left alone."""
    from server.services import folder_rules
    path = await folder_rules.listed(conversation_id, body.file)
    if path is None:
        raise HTTPException(409, "rules_file_not_listed")
    async with db_session.AsyncSessionLocal() as db:
        try:
            in_file = await folder_rules.remove_rule(db, path, body.lesson_id, body.line)
        except folder_rules.RuleRefused:
            raise HTTPException(409, "rules_file_refused") from None
        if in_file is None:
            raise HTTPException(409, "rule_not_added")
        row = await db.get(Lesson, body.lesson_id)
        evidence = dict(row.evidence or {}) if row is not None else {}
        record = evidence.get(lessons.RULE_RECORD) or {}
        if evidence.get(lessons.RULE_OFFER) == "added" and (record.get("path"), record.get("line")) == (str(path), body.line):
            row.evidence = {**evidence, lessons.RULE_OFFER: "removed"}
        await db.commit()
    return {"state": "removed", "file": body.file, "in_file": in_file}


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
