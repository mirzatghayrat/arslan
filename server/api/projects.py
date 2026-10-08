"""Projects in two layers (0.1.56): the board, a project's plan, and how it moves.

The project row itself (name, type, summary, folder, collections) keeps its routes in
companion.py; everything here writes the plan's own tables and `plan_version`, never
`projects.version` (which pins running tasks).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from arslan.companion.memory import MemoryError
from server.api.companion import USER, _repository
from server.auth import require_auth
from server.db.models import ArslanMessage, ConversationContext, Project, ProjectEvent
from server.services import project_plan, project_templates
from server.services.project_plan import PlanError

router = APIRouter(dependencies=[Depends(require_auth)])

FILES_LIMIT = 200


def _error(exc: PlanError) -> HTTPException:
    status = 404 if exc.code.endswith("not_found") else 409 if "conflict" in exc.code or exc.code in {
        "proposal_decided", "only_latest_advance", "no_current_level", "no_levels"} else 422
    return HTTPException(status, detail={"code": exc.code})


async def _project(repo, project_id: str) -> Project:
    row = await repo.db.get(Project, project_id)
    if row is None or row.owner_id != USER.owner_id:
        raise MemoryError("project_not_available")
    return row


@router.get("/project-templates")
async def templates(lang: str | None = None) -> list[dict]:
    language = project_templates.lang_of(lang)
    return [{"key": key, "levels": [{"name": names[language], "band": band} for band, names in levels]}
            for key, levels in project_templates.TEMPLATES.items()]


class DraftIn(BaseModel):
    template: Annotated[str, Field(max_length=30)]
    finish_line: Annotated[str, Field(max_length=400)] = ""
    lang: Annotated[str, Field(max_length=10)] | None = None


@router.post("/projects/draft")
async def draft(body: DraftIn) -> dict:
    """§3.1 the deterministic draft. (P3 adds the model's adaptation on top.)"""
    return {"levels": project_templates.draft(body.template, body.finish_line, body.lang), "source": "template"}


@router.get("/projects/board")
async def board(repo=Depends(_repository, scope="function")) -> dict:
    return await project_plan.board(repo.db, USER.owner_id)


@router.get("/projects/{project_id}/plan")
async def get_plan(project_id: str, repo=Depends(_repository, scope="function")) -> dict:
    return await project_plan.plan_of(repo.db, await _project(repo, project_id))


class PlanIn(BaseModel):
    expected_version: Annotated[int, Field(ge=0)]
    levels: list[dict[str, Any]]


@router.put("/projects/{project_id}/plan")
async def put_plan(project_id: str, body: PlanIn, repo=Depends(_repository, scope="function")) -> dict:
    project = await _project(repo, project_id)
    try:
        return await project_plan.put_plan(repo.db, project, body.expected_version, body.levels)
    except PlanError as exc:
        raise _error(exc) from exc


@router.post("/projects/{project_id}/checkpoints/{checkpoint_id}/{action}")
async def checkpoint(project_id: str, checkpoint_id: str, action: Literal["tick", "untick"],
                     repo=Depends(_repository, scope="function")) -> dict:
    project = await _project(repo, project_id)
    try:
        if action == "tick":
            await project_plan.tick(repo.db, project, checkpoint_id, actor="user")
        else:
            await project_plan.untick(repo.db, project, checkpoint_id, actor="user")
    except PlanError as exc:
        raise _error(exc) from exc
    return await project_plan.plan_of(repo.db, project)


@router.post("/projects/{project_id}/advance")
async def advance(project_id: str, repo=Depends(_repository, scope="function")) -> dict:
    """The user clears the current level by hand."""
    project = await _project(repo, project_id)
    try:
        await project_plan.advance(repo.db, project, actor="user")
    except PlanError as exc:
        raise _error(exc) from exc
    return await project_plan.plan_of(repo.db, project)


@router.post("/projects/{project_id}/proposals/{event_id}/{decision}")
async def decide(project_id: str, event_id: str, decision: Literal["accept", "decline"],
                 repo=Depends(_repository, scope="function")) -> dict:
    project = await _project(repo, project_id)
    try:
        await project_plan.decide(repo.db, project, event_id, decision == "accept")
    except PlanError as exc:
        raise _error(exc) from exc
    return await project_plan.plan_of(repo.db, project)


@router.post("/projects/{project_id}/events/{event_id}/undo")
async def undo(project_id: str, event_id: str, repo=Depends(_repository, scope="function")) -> dict:
    project = await _project(repo, project_id)
    try:
        await project_plan.undo(repo.db, project, event_id)
    except PlanError as exc:
        raise _error(exc) from exc
    return await project_plan.plan_of(repo.db, project)


class StageIn(BaseModel):
    stage: Literal["active", "done", "dropped"] | None = None
    paused: bool | None = None


@router.put("/projects/{project_id}/stage")
async def stage(project_id: str, body: StageIn, repo=Depends(_repository, scope="function")) -> dict:
    project = await _project(repo, project_id)
    try:
        await project_plan.set_stage(repo.db, project, stage=body.stage, paused=body.paused)
    except PlanError as exc:
        raise _error(exc) from exc
    return await project_plan.plan_of(repo.db, project)


@router.get("/projects/{project_id}/events")
async def events(project_id: str, limit: int = Query(20, ge=1, le=100),
                 repo=Depends(_repository, scope="function")) -> list[dict]:
    """What happened, newest first — the page's "Arslan 最近做的" filters actor arslan."""
    project = await _project(repo, project_id)
    rows = (await repo.db.execute(select(ProjectEvent).where(
        ProjectEvent.project_id == project.id, ProjectEvent.kind != "activity",
    ).order_by(ProjectEvent.created_at.desc()).limit(limit))).scalars().all()
    return [{"id": r.id, "kind": r.kind, "actor": r.actor, "payload": r.payload, "outcome": r.outcome,
             "created_at": r.created_at.isoformat() + "Z"} for r in rows]


@router.get("/projects/{project_id}/conversations")
async def conversations(project_id: str, repo=Depends(_repository, scope="function")) -> list[dict]:
    """Every conversation set to this project, most recently active first."""
    project = await _project(repo, project_id)
    ids = (await repo.db.execute(select(ConversationContext.id).where(
        ConversationContext.project_id == project.id, ConversationContext.owner_id == USER.owner_id,
    ))).scalars().all()
    if not ids:
        return []
    agg = {cid: (count, last) for cid, count, last in (await repo.db.execute(
        select(ArslanMessage.conversation_id, func.count(ArslanMessage.id), func.max(ArslanMessage.timestamp))
        .where(ArslanMessage.conversation_id.in_(ids)).group_by(ArslanMessage.conversation_id))).all()}
    first = dict((await repo.db.execute(
        select(ArslanMessage.conversation_id, func.min(ArslanMessage.id))
        .where(ArslanMessage.conversation_id.in_(ids), ArslanMessage.role == "user")
        .group_by(ArslanMessage.conversation_id))).all())
    openings = dict((await repo.db.execute(select(ArslanMessage.id, ArslanMessage.content).where(
        ArslanMessage.id.in_(list(first.values()))))).all()) if first else {}
    out = []
    for cid in ids:
        count, last = agg.get(cid, (0, None))
        text = " ".join(str(openings.get(first.get(cid), "") or "").split())
        out.append({"conversation_id": cid, "messages": count,
                    "last_at": last.isoformat() + "Z" if last else None, "opening": text[:60] or None})
    return sorted(out, key=lambda r: r["last_at"] or "", reverse=True)


def project_folder(project: Project) -> Path | None:
    """The project's folder (0.1.56: `workspace_ref` is it). Must exist and be a directory."""
    raw = (project.workspace_ref or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        path = path.resolve()
    except OSError:
        return None
    return path if path.is_dir() else None


@router.get("/projects/{project_id}/files")
async def files(project_id: str, repo=Depends(_repository, scope="function")) -> dict:
    """The folder's top level: names only, folders first, secrets-named files left out."""
    from server.services.workspace_paths import is_secret_name
    project = await _project(repo, project_id)
    folder = project_folder(project)
    if folder is None:
        return {"folder": project.workspace_ref or None, "exists": False, "entries": [], "truncated": False}
    entries = []
    truncated = False
    for child in sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith(".") or is_secret_name(child.name):
            continue
        if len(entries) >= FILES_LIMIT:
            truncated = True
            break
        entries.append({"name": child.name, "dir": child.is_dir()})
    return {"folder": str(folder), "exists": True, "entries": entries, "truncated": truncated}
