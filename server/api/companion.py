"""Authenticated project and personal-memory controls; all text errors are codes."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, model_validator
from sqlalchemy import select, update

from arslan.companion.contracts import Contract
from arslan.companion.memory import MemoryActor, MemoryError, MemoryScope, MemoryWrite
from server.auth import require_auth
from server.db.models import Collection, ConversationContext, MemoryEntry, MemoryProposal, Project
from server.services.memory_repository import repository

router = APIRouter(dependencies=[Depends(require_auth)])
USER = MemoryActor(origin="user")


def _error(exc: MemoryError):
    status = 409
    if exc.code in {"memory_not_found", "proposal_not_found", "project_not_available"}:
        status = 404
    elif exc.code in {"memory_scope_denied", "user_confirmation_required", "learning_disabled"}:
        status = 403
    elif exc.code in {"credentials_not_memory", "sensitive_confirmation_required"}:
        status = 422
    elif exc.code == "memory_deleted":
        status = 410
    return HTTPException(status, detail={"code": exc.code})


async def _repository():
    try:
        async with repository() as repo:
            yield repo
    except MemoryError as exc:
        raise _error(exc) from exc


class AppBinding(Contract):
    app_id: Annotated[str, Field(pattern=r"^[0-9]{1,30}$")] | None = None
    bundle_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    connection_id: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    # Only metadata and opaque connection reference; no private key or token.


class ProjectInput(Contract):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    kind: Literal["general", "software", "research", "design"] = "general"
    summary: Annotated[str, Field(max_length=10000)] = ""
    workspace_ref: Annotated[str, Field(max_length=200)] | None = None
    collection_ids: tuple[Annotated[int, Field(gt=0, strict=True)], ...] = ()
    app_binding: AppBinding | None = None

    @model_validator(mode="after")
    def no_credentials(self):
        from arslan.companion.content_policy import contains_credential
        if any(contains_credential(value) for value in (self.name, self.summary, self.workspace_ref or "")):
            raise ValueError("credentials_not_project_metadata")
        return self


class ProjectEdit(Contract):
    expected_version: Annotated[int, Field(gt=0, strict=True)]
    project: ProjectInput
    status: Literal["active", "archived"] = "active"


def _project(row):
    return {"id": row.id, "name": row.name, "kind": row.kind, "summary": row.summary,
            "workspace_ref": row.workspace_ref, "collection_ids": row.collection_ids,
            "app_binding": row.app_binding, "status": row.status, "version": row.version,
            "created_at": row.created_at.isoformat() + "Z", "updated_at": row.updated_at.isoformat() + "Z"}


def _project_values(body):
    data = body.model_dump(mode="json", exclude={"schema_version"})
    if not data["name"].strip():
        raise HTTPException(422, detail={"code": "project_name_required"})
    data["name"] = data["name"].strip()
    return data


async def _validate_collections(repo, identifiers):
    if identifiers:
        existing = set((await repo.db.execute(select(Collection.id).where(Collection.id.in_(identifiers)))).scalars())
        if existing != set(identifiers):
            raise HTTPException(422, detail={"code": "project_collection_not_found"})


@router.get("/projects")
async def list_projects(include_archived: bool = False, repo=Depends(_repository)):
    query = select(Project).where(Project.owner_id == USER.owner_id)
    if not include_archived:
        query = query.where(Project.status == "active")
    rows = (await repo.db.execute(query.order_by(Project.updated_at.desc(), Project.id))).scalars().all()
    return [_project(row) for row in rows]


@router.post("/projects", status_code=201)
async def create_project(body: ProjectInput, repo=Depends(_repository)):
    await _validate_collections(repo, body.collection_ids)
    row = Project(id=str(uuid4()), owner_id=USER.owner_id, **_project_values(body))
    repo.db.add(row)
    await repo.db.flush()
    return _project(row)


@router.put("/projects/{project_id}")
async def edit_project(project_id: str, body: ProjectEdit, repo=Depends(_repository)):
    row = await repo.db.get(Project, project_id)
    if row is None or row.owner_id != USER.owner_id:
        raise MemoryError("project_not_available")
    await _validate_collections(repo, body.project.collection_ids)
    result = await repo.db.execute(update(Project).where(
        Project.id == project_id, Project.owner_id == USER.owner_id, Project.version == body.expected_version,
    ).values(**_project_values(body.project), status=body.status, version=body.expected_version + 1,
             updated_at=datetime.utcnow()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise MemoryError("project_version_conflict")
    await repo.db.refresh(row)
    return _project(row)


class ConversationSettings(Contract):
    expected_version: Annotated[int, Field(ge=0, strict=True)]
    project_id: str | None = None
    no_memory: bool = False
    no_learning: bool = False
    temporary: bool = False
    cloud_memory_allowed: bool = False
    allow_sensitive: bool = False


def _conversation(row, conversation_id):
    return {"conversation_id": conversation_id, "version": row.version if row else 0,
            "project_id": row.project_id if row else None,
            **{key: bool(getattr(row, key, False)) for key in (
                "no_memory", "no_learning", "temporary", "cloud_memory_allowed", "allow_sensitive")}}


@router.get("/conversations/{conversation_id}/context")
async def conversation_context(conversation_id: str, repo=Depends(_repository)):
    row = await repo.db.get(ConversationContext, conversation_id)
    if row and row.owner_id != USER.owner_id:
        raise HTTPException(404, detail={"code": "conversation_not_found"})
    return _conversation(row, conversation_id)


@router.get("/conversations/{conversation_id}/context/receipts")
async def context_receipts(conversation_id: str, limit: int = Query(20, ge=1, le=100), repo=Depends(_repository)):
    from server.db.models import ContextReceiptRecord
    rows = (await repo.db.execute(select(ContextReceiptRecord).where(
        ContextReceiptRecord.owner_id == USER.owner_id, ContextReceiptRecord.conversation_id == conversation_id,
    ).order_by(ContextReceiptRecord.created_at.desc()).limit(limit))).scalars().all()
    return [{"receipt": row.receipt, "created_at": row.created_at.isoformat() + "Z"} for row in rows]


@router.put("/conversations/{conversation_id}/context")
async def update_conversation_context(conversation_id: str, body: ConversationSettings, repo=Depends(_repository)):
    from server.services import run_registry, turn_journal
    if len(conversation_id) > 100 or not conversation_id.strip():
        raise HTTPException(422, detail={"code": "invalid_conversation_id"})
    if run_registry.active_for(conversation_id) or turn_journal.active(conversation_id):
        raise HTTPException(409, detail={"code": "conversation_running"})
    if body.project_id:
        project = await repo.db.get(Project, body.project_id)
        if project is None or project.owner_id != USER.owner_id or project.status != "active":
            raise MemoryError("project_not_available")
    row = await repo.db.get(ConversationContext, conversation_id)
    if row and row.owner_id != USER.owner_id:
        raise HTTPException(404, detail={"code": "conversation_not_found"})
    if body.temporary:
        from server.db.models import ArslanMessage
        if await repo.db.scalar(select(ArslanMessage.id).where(
                ArslanMessage.conversation_id == conversation_id).limit(1)):
            raise HTTPException(409, detail={"code": "temporary_requires_new_conversation"})
    values = body.model_dump(exclude={"schema_version", "expected_version"})
    if row is None:
        if body.expected_version != 0:
            raise HTTPException(409, detail={"code": "conversation_version_conflict"})
        from sqlalchemy.dialects.sqlite import insert
        result = await repo.db.execute(insert(ConversationContext).values(
            id=conversation_id, owner_id=USER.owner_id, version=1, **values,
        ).on_conflict_do_nothing())
    else:
        # Temporary conversations never become persistable after their first turn.
        if row.temporary and not body.temporary:
            raise HTTPException(409, detail={"code": "temporary_mode_immutable"})
        result = await repo.db.execute(update(ConversationContext).where(
            ConversationContext.id == conversation_id, ConversationContext.version == body.expected_version,
        ).values(**values, version=body.expected_version + 1, updated_at=datetime.utcnow())
          .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(409, detail={"code": "conversation_version_conflict"})
    if body.no_learning or body.temporary or not body.cloud_memory_allowed:
        from server.db.models import Run
        await repo.db.execute(update(Run).where(Run.conversation_id == conversation_id)
                              .values(no_learning=True))
    await repo.db.flush()
    if row:
        await repo.db.refresh(row)
    else:
        row = await repo.db.get(ConversationContext, conversation_id)
    return _conversation(row, conversation_id)


@router.get("/memory/entries")
async def list_memory(scope_kind: str | None = None, scope_id: str | None = None,
                      include_deleted: bool = False, limit: int = Query(200, ge=1, le=500),
                      offset: int = Query(0, ge=0), repo=Depends(_repository)):
    try:
        scope = MemoryScope(kind=scope_kind, id=scope_id) if scope_kind else None
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "invalid_memory_scope"}) from exc
    return await repo.list_entries(scope=scope, include_deleted=include_deleted, limit=limit, offset=offset)


@router.post("/memory/entries", status_code=201)
async def create_memory(body: MemoryWrite, repo=Depends(_repository)):
    return await repo.create(body, USER)


@router.get("/memory/entries/{entry_id}")
async def get_memory(entry_id: str, repo=Depends(_repository)):
    return await repo.present(await repo.get(entry_id))


class MemoryEdit(Contract):
    expected_version: Annotated[int, Field(gt=0, strict=True)]
    memory: MemoryWrite
    confirm_scope_change: bool = False


@router.put("/memory/entries/{entry_id}")
async def edit_memory(entry_id: str, body: MemoryEdit, repo=Depends(_repository)):
    return await repo.revise(entry_id, body.expected_version, body.memory, USER,
                             confirm_scope_change=body.confirm_scope_change)


class MemoryStatus(Contract):
    expected_version: Annotated[int, Field(gt=0, strict=True)]
    status: Literal["active", "paused"]


@router.post("/memory/entries/{entry_id}/status")
async def memory_status(entry_id: str, body: MemoryStatus, repo=Depends(_repository)):
    return await repo.set_status(entry_id, body.expected_version, body.status, USER)


@router.delete("/memory/entries/{entry_id}")
async def delete_memory(entry_id: str, expected_version: int = Query(..., ge=1), repo=Depends(_repository)):
    return await repo.delete_entry(entry_id, expected_version, USER)


@router.get("/memory/entries/{entry_id}/history")
async def memory_history(entry_id: str, repo=Depends(_repository)):
    return await repo.history(entry_id)


@router.get("/memory/proposals")
async def memory_proposals(limit: int = Query(200, ge=1, le=500),
                           offset: int = Query(0, ge=0), repo=Depends(_repository)):
    rows = (await repo.db.execute(select(MemoryProposal, MemoryEntry).join(
        MemoryEntry, MemoryEntry.id == MemoryProposal.target_entry_id,
    ).where(MemoryProposal.kind == "memory_v2", MemoryProposal.status == "pending",
            MemoryEntry.owner_id == USER.owner_id, MemoryEntry.status != "deleted")
        .order_by(MemoryProposal.created_at.desc(), MemoryProposal.id.desc()).limit(limit).offset(offset))).all()
    return [{"id": proposal.id, "target_id": entry.id, "target_version": proposal.target_version,
             "candidate": proposal.candidate, "entry": await repo.present(entry),
             "reason": proposal.reason} for proposal, entry in rows]


class ProposalDecision(Contract):
    accept: bool
    sensitive_acknowledged: bool = False
    use_policy: Literal["local_only", "cloud_allowed"] = "local_only"


@router.post("/memory/proposals/{proposal_id}/resolve")
async def resolve_memory_proposal(proposal_id: int, body: ProposalDecision, repo=Depends(_repository)):
    return await repo.resolve_proposal(proposal_id, actor=USER, **body.model_dump(exclude={"schema_version"}))
