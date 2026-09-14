"""Authenticated task inspection, manual acceptance and recovery controls."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select

from arslan.companion.content_policy import contains_credential
from arslan.companion.contracts import Contract, ResourceRef, TaskSpec
from server.auth import require_auth
from server.db.models import CompanionTask, TaskAction, TaskAttempt, TaskWorker
from server.services import task_service
from server.services.task_repository import TaskError, identity, repository

router = APIRouter(dependencies=[Depends(require_auth)])


def api_error(exc: TaskError):
    status = 404 if exc.code == "task_not_found" else 422 if exc.code.startswith("invalid_") else 409
    return HTTPException(status, detail={"code": exc.code})


async def task_repository():
    try:
        async with repository() as repo:
            yield repo
    except TaskError as exc:
        raise api_error(exc) from exc


class Version(Contract):
    expected_version: Annotated[int, Field(ge=1, strict=True)]


class Cancellation(Contract):
    expected_version: Annotated[int, Field(ge=1, strict=True)] | None = None


class Revision(Version):
    spec: TaskSpec


@router.put("/tasks/{task_id}")
async def revise_task(task_id: str, body: Revision, repo=Depends(task_repository)):
    return await repo.revise(task_id, body.expected_version, body.spec)


@router.get("/tasks")
async def list_tasks(conversation_id: str | None = None, limit: int = Query(20, ge=1, le=100),
                     offset: int = Query(0, ge=0), repo=Depends(task_repository)):
    query = select(CompanionTask).where(CompanionTask.owner_id == "local")
    if conversation_id is not None:
        query = query.where(CompanionTask.conversation_id == conversation_id)
    rows = (await repo.db.execute(query.order_by(CompanionTask.created_at.desc(), CompanionTask.id)
                                  .limit(limit).offset(offset))).scalars().all()
    return [await repo.present(row) for row in rows]


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str, repo=Depends(task_repository)):
    row = await repo.get(task_id)
    attempts = (await repo.db.execute(select(TaskAttempt).where(TaskAttempt.task_id == row.id)
                                     .order_by(TaskAttempt.number))).scalars().all()
    actions = (await repo.db.execute(select(TaskAction).where(TaskAction.task_id == row.id)
                                    .order_by(TaskAction.created_at, TaskAction.id))).scalars().all()
    from server.services.task_workers import present as present_worker
    from server.services.task_validation import latest_report
    workers = (await repo.db.scalars(select(TaskWorker).where(TaskWorker.task_id == row.id)
                                    .order_by(TaskWorker.created_at, TaskWorker.id))).all()
    return {**await repo.present(row), "checkpoint": await repo.latest_checkpoint(row.id),
            "validation": await latest_report(repo, row),
            "workers": [present_worker(worker) for worker in workers],
            "attempts": [{"id": attempt.id, "number": attempt.number, "status": attempt.status,
                          "run_ids": attempt.run_ids} for attempt in attempts],
            "actions": [{"id": action.id, "version": action.version, "tool_key": action.tool_key,
                         "effect": action.effect, "status": action.status, "evidence": action.evidence,
                         "error_code": action.error_code} for action in actions]}


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                      repo=Depends(task_repository)):
    return await repo.events(task_id, after, limit)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, body: Cancellation):
    try:
        return await task_service.cancel(task_id, body.expected_version)
    except TaskError as exc:
        raise api_error(exc) from exc


@router.post("/tasks/{task_id}/accept")
async def accept_task(task_id: str, body: Version, repo=Depends(task_repository)):
    return await repo.accept_review(task_id, body.expected_version)


class Reconciliation(Version):
    applied: bool
    note: Annotated[str, Field(min_length=10, max_length=2000)]


@router.post("/tasks/{task_id}/actions/{action_id}/reconcile")
async def reconcile_action(task_id: str, action_id: str, body: Reconciliation, repo=Depends(task_repository)):
    # This is explicit human review over authenticated REST, not a model tool.
    # The explanatory note becomes a durable review document referenced by the
    # journal. We do not claim that it is automated third-party verification.
    if contains_credential(body.note):
        raise HTTPException(422, detail={"code": "credentials_not_review_data"})
    row = await repo.get(task_id)
    if row.phase in {"running", "verifying"}:
        raise TaskError("task_still_running")
    review_id = f"human-review:{identity()}"
    proof = ResourceRef(id=review_id, kind="document", revision=1,
                        locator=f"/api/v1/tasks/{row.id}/events?after={row.sequence}")
    await repo._advance(row, "human_action_review", payload={
        "review_id": review_id, "reviewer": "local", "note": body.note, "applied": body.applied})
    await repo.reconcile_action(task_id, action_id, expected_version=body.expected_version,
                               applied=body.applied, evidence=(proof,))
    return await repo.present(row)
