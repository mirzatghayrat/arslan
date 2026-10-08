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
    #: §3.2 one model call, only when the user asks; `levels` = what the editor shows now.
    refine: bool = False
    levels: list[dict[str, Any]] | None = None


@router.post("/projects/draft")
async def draft(body: DraftIn) -> dict:
    """§3.1 the template draft, always without a model; with `refine`, the model adapts the
    given levels (or the template draft) to the finish line. A failed refine says so and
    returns the levels it was given, unchanged."""
    base = body.levels or project_templates.draft(body.template, body.finish_line, body.lang)
    if not body.refine:
        return {"levels": base, "source": "template"}
    from server.services import project_drafter
    refined = await project_drafter.refine(body.template, body.finish_line, body.lang, base)
    if refined is None:
        return {"levels": base, "source": "template", "refine_failed": True}
    return {"levels": refined, "source": "model"}


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


class HandoffIn(BaseModel):
    checkpoint_id: Annotated[str, Field(min_length=1, max_length=40)]
    conversation_id: Annotated[str, Field(min_length=1, max_length=50)]


@router.post("/projects/{project_id}/handoff")
async def handoff(project_id: str, body: HandoffIn, repo=Depends(_repository, scope="function")) -> dict:
    """§4.4 "交给 Arslan 起头": a background job in this conversation that ends done ticks
    the checkpoint. The conversation must already be set to this project."""
    from server.services import project_evidence
    project = await _project(repo, project_id)
    owner = (await repo.db.execute(select(ConversationContext.project_id).where(
        ConversationContext.id == body.conversation_id, ConversationContext.owner_id == USER.owner_id))).scalar()
    if owner != project.id:
        raise HTTPException(409, detail={"code": "conversation_not_in_project"})
    try:
        event = await project_evidence.record_handoff(repo.db, project, body.checkpoint_id, body.conversation_id)
    except PlanError as exc:
        raise _error(exc) from exc
    return {"id": event.id}


@router.post("/projects/{project_id}/advance")
async def advance(project_id: str, repo=Depends(_repository, scope="function")) -> dict:
    """The user clears the current level by hand."""
    project = await _project(repo, project_id)
    try:
        await project_plan.advance(repo.db, project, actor="user")
    except PlanError as exc:
        raise _error(exc) from exc
    return await project_plan.plan_of(repo.db, project)


class DecideIn(BaseModel):
    #: §5 the optional line on a decline ("还想再试一版"); it becomes a plan rule (§6 c).
    note: Annotated[str, Field(max_length=200)] | None = None


@router.post("/projects/{project_id}/proposals/{event_id}/{decision}")
async def decide(project_id: str, event_id: str, decision: Literal["accept", "decline"],
                 body: DecideIn | None = None, repo=Depends(_repository, scope="function")) -> dict:
    project = await _project(repo, project_id)
    try:
        await project_plan.decide(repo.db, project, event_id, decision == "accept",
                                  note=body.note if body else None)   # decide() reads it on a decline only
    except PlanError as exc:
        raise _error(exc) from exc
    return await project_plan.plan_of(repo.db, project)


class NoteIn(BaseModel):
    note: Annotated[str, Field(min_length=1, max_length=200)]


@router.post("/projects/{project_id}/proposal-notes/{event_id}")   # not under /proposals: {decision} would catch it
async def note(project_id: str, event_id: str, body: NoteIn, repo=Depends(_repository, scope="function")) -> dict:
    """The optional line said after declining (the board's "想补一句吗？")."""
    project = await _project(repo, project_id)
    try:
        await project_plan.add_note(repo.db, project, event_id, body.note)
    except PlanError as exc:
        raise _error(exc) from exc
    return await project_plan.plan_of(repo.db, project)


@router.post("/projects/{project_id}/plan-proposals/{event_id}/{decision}")
async def decide_plan(project_id: str, event_id: str, decision: Literal["accept", "decline"],
                      repo=Depends(_repository, scope="function")) -> dict:
    project = await _project(repo, project_id)
    try:
        await project_plan.decide_plan(repo.db, project, event_id, decision == "accept")
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


# ── what Arslan learned (§5, §6) ─────────────────────────────────────────────

@router.get("/project-habits")
async def habits(repo=Depends(_repository, scope="function")) -> dict:
    from server.services import project_habits
    return await project_habits.sheet(repo.db, USER.owner_id)


class RuleIn(BaseModel):
    enabled: bool


@router.put("/project-habits/rules/{rule_id}")
async def set_rule(rule_id: str, body: RuleIn, repo=Depends(_repository, scope="function")) -> dict:
    from server.db.models import ProjectHabit
    from server.services import project_habits
    row = await repo.db.get(ProjectHabit, rule_id)
    if row is None or row.owner_id != USER.owner_id or row.kind != "plan_rule":
        raise HTTPException(404, detail={"code": "rule_not_found"})
    row.enabled = body.enabled
    await repo.db.flush()
    return await project_habits.sheet(repo.db, USER.owner_id)


class PaceIn(BaseModel):
    template: Literal[tuple(project_templates.TEMPLATES)]  # type: ignore[valid-type]
    band: Literal["shaping", "doing", "done"]
    #: None clears the override (back to the median).
    days: Annotated[float, Field(gt=0, le=365)] | None = None


@router.put("/project-habits/pace")
async def set_pace(body: PaceIn, repo=Depends(_repository, scope="function")) -> dict:
    from server.services import project_habits
    await project_habits.set_pace(repo.db, USER.owner_id, body.template, body.band, body.days)
    return await project_habits.sheet(repo.db, USER.owner_id)


class AutoAdvanceIn(BaseModel):
    on: bool
    #: ask = the one question at 10 in a row; offer = "turn it off?" after 2 undos; settings = the switch.
    answered: Literal["ask", "offer", "settings"] = "settings"


@router.put("/project-habits/auto-advance")
async def auto_advance(body: AutoAdvanceIn, repo=Depends(_repository, scope="function")) -> dict:
    """Only the user turns auto-advance on (§5): on 好 to the ask, or the Settings switch."""
    from server.services import project_habits, settings_service
    db = repo.db
    await settings_service._set_raw(db, "projects_auto_advance", "true" if body.on else "false")
    if body.answered == "ask":
        await settings_service._set_raw(db, project_plan.ASKED_KEY, "yes" if body.on else "no")
    if body.answered == "offer" and body.on:
        # Keep it on: do not offer again for the same run of undos.
        miss = (await project_plan.shadow(db)).last_miss
        if miss:
            await settings_service._set_raw(db, project_plan.KEPT_KEY, miss["id"])
    await db.flush()
    return await project_habits.sheet(db, USER.owner_id)
