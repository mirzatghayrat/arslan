"""Authenticated, explicit-user controls for immutable recipes and task runs."""
from __future__ import annotations

import copy
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from server.auth import require_auth
from server.db import session as db_session
from server.db.models import RecipeExecution, RecipeVersion, Spawn
from server.services import recipes

router = APIRouter(dependencies=[Depends(require_auth)])


def _error(status, code):
    return HTTPException(status, detail={"code": f"recipes.{code}"})


def _version(row):
    return {"id": row.id, "key": row.key, "version": row.version, "name": row.name,
            "spec": row.spec, "created_at": row.created_at}


def _execution(row):
    return {"id": row.id, "recipe_id": row.recipe_id, "input": row.input,
            "status": row.status, "checkpoint": row.checkpoint, "run_id": row.run_id,
            "error": row.error, "created_at": row.created_at, "updated_at": row.updated_at}


async def _launch(db, row):
    try:
        recipes.launch(row.id)
    except ValueError:
        row.status, row.error = "interrupted", "Active execution limit reached; resume when a slot is free."
        await db.commit()
        raise _error(409, "active_limit") from None


@router.get("/recipes")
async def list_recipes():
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(RecipeVersion).order_by(RecipeVersion.id.desc()).limit(200))).scalars()
        return [_version(row) for row in rows]


@router.post("/recipes/{key}/versions", status_code=201)
async def save_version(key: str, spec: recipes.Spec):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,59}", key):
        raise _error(422, "invalid_key")
    async with db_session.AsyncSessionLocal() as db:
        ids = {step.spawn_id for step in spec.steps}
        available = set((await db.execute(select(Spawn.id).where(Spawn.id.in_(ids)))).scalars())
        if ids != available:
            raise _error(422, "spawn_missing")
        latest = (await db.execute(select(func.max(RecipeVersion.version)).where(RecipeVersion.key == key))).scalar()
        row = RecipeVersion(key=key, version=(latest or 0) + 1, name=spec.name, spec=spec.model_dump())
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            raise _error(409, "version_conflict") from None
        await db.refresh(row)
        return _version(row)


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe_id: int = Field(gt=0)
    input: str = Field(min_length=1, max_length=8000)
    request_key: str = Field(min_length=8, max_length=80)


@router.post("/recipe-executions", status_code=202)
async def start_execution(body: Start):
    async with db_session.AsyncSessionLocal() as db:
        existing = (await db.execute(select(RecipeExecution).where(
            RecipeExecution.request_key == body.request_key))).scalar_one_or_none()
        if existing is not None:
            if existing.recipe_id != body.recipe_id or existing.input != body.input:
                raise _error(409, "request_conflict")
            return _execution(existing)
        if sum(recipes.active(key) for key in recipes._active) >= 4:
            raise _error(409, "active_limit")
        recipe = await db.get(RecipeVersion, body.recipe_id)
        if recipe is None:
            raise _error(404, "not_found")
        row = RecipeExecution(recipe_id=recipe.id, input=body.input, request_key=body.request_key,
                              status="queued", checkpoint={})
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            raise _error(409, "request_conflict") from None
        await db.refresh(row)
        await _launch(db, row)
        return _execution(row)


@router.get("/recipe-executions")
async def list_executions():
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(RecipeExecution).order_by(RecipeExecution.id.desc()).limit(100))).scalars()
        return [_execution(row) for row in rows]


@router.get("/recipe-executions/{execution_id}")
async def get_execution(execution_id: int):
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(RecipeExecution, execution_id)
        if row is None:
            raise _error(404, "execution_missing")
        return _execution(row)


class Resume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve_steps: list[str] = Field(default_factory=list, max_length=16)
    retry_unfinished: bool = False


@router.post("/recipe-executions/{execution_id}/resume", status_code=202)
async def resume_execution(execution_id: int, body: Resume):
    if recipes.active(execution_id):
        raise _error(409, "already_running")
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(RecipeExecution, execution_id)
        if row is None:
            raise _error(404, "execution_missing")
        if row.status not in {"waiting_approval", "failed", "interrupted"}:
            raise _error(409, "not_resumable")
        if row.status in {"failed", "interrupted"} and not body.retry_unfinished:
            raise _error(409, "retry_confirmation_required")
        checkpoint = copy.deepcopy(row.checkpoint or {})
        nodes = checkpoint.get("steps", {})
        waiting = {key for key, node in nodes.items() if node.get("status") == "waiting_approval"}
        if not set(body.approve_steps) <= waiting:
            raise _error(422, "approval_not_waiting")
        if row.status == "waiting_approval" and not body.approve_steps:
            raise _error(422, "approval_required")
        checkpoint["approved"] = sorted(set(checkpoint.get("approved", [])) | set(body.approve_steps))
        for node in nodes.values():
            if node.get("status") in {"failed", "interrupted", "running"}:
                node["status"] = "pending"
        row.checkpoint, row.status, row.error = checkpoint, "queued", None
        await db.commit()
        await _launch(db, row)
        return _execution(row)


@router.post("/recipe-executions/{execution_id}/cancel")
async def cancel_execution(execution_id: int):
    if not recipes.cancel(execution_id):
        raise _error(409, "not_running")
    return {"cancel_requested": True}
