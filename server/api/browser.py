"""Authenticated, user-initiated public webpage previews (no model tool surface)."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from server.auth import require_auth
from server.db import session as db_session
from server.db.models import Run
from server.services import host_run, managed_browser, artifact_store
from server.services import browser_reader
from server.services.browser_proxy import validate_url

router = APIRouter(dependencies=[Depends(require_auth)])
_tasks: set[asyncio.Task] = set()
_launch_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


@router.get("/browser/status")
async def browser_status():
    return await asyncio.to_thread(managed_browser.status)


@router.post("/browser/setup")
async def browser_setup():
    try:
        return await managed_browser.setup()
    except (ValueError, RuntimeError, OSError, TimeoutError):
        logger.exception("Managed browser setup failed")
        raise HTTPException(503, detail={"code": "browser.setup_failed"}) from None


class Visit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=4000)
    request_key: str = Field(min_length=8, max_length=80)


@router.post("/browser/visits", status_code=202)
async def start_visit(body: Visit):
    try:
        validate_url(body.url)
    except ValueError:
        raise HTTPException(422, detail={"code": "browser.invalid_url"}) from None
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", body.request_key):
        raise HTTPException(422, detail={"code": "browser.invalid_request"})
    conversation = "browser:" + body.request_key
    async with _launch_lock:
        async with db_session.AsyncSessionLocal() as db:
            existing = (await db.execute(select(Run).where(
                Run.conversation_id == conversation))).scalars().first()
            if existing is not None:
                if existing.user_message != body.url:
                    raise HTTPException(409, detail={"code": "browser.request_conflict"})
                return {"run_id": existing.id}
        if len(_tasks) >= 2:
            raise HTTPException(409, detail={"code": "browser.busy"})
        state = await asyncio.to_thread(managed_browser.status)
        if not state["ready"]:
            raise HTTPException(409, detail={"code": "browser." + state["reason"]})
        started = asyncio.get_running_loop().create_future()

        def emit(event):
            if event.get("run_id") and not started.done():
                started.set_result(event["run_id"])

        async def work(capture):
            result = await managed_browser.preview(body.url)
            # Exact snapshot is an untrusted webpage, never instructions for the host.
            capture({"type": "stream_chunk", "content": json.dumps(result, ensure_ascii=False)})
            return json.dumps(result, ensure_ascii=False)

        async def lifecycle():
            try:
                await host_run.execute(conversation, body.url, emit, work, name="Browser preview")
            except BaseException as exc:
                if not started.done():
                    started.set_exception(exc)
                if not isinstance(exc, asyncio.CancelledError):
                    logger.warning("Browser preview failed: %s", exc)

        task = asyncio.create_task(lifecycle())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        try:
            run_id = await asyncio.wait_for(asyncio.shield(started), 10)
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        return {"run_id": run_id}


@router.get("/browser/visits/{run_id}")
async def get_visit(run_id: int):
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(Run, run_id)
        if row is None or not (row.conversation_id or "").startswith("browser:"):
            raise HTTPException(404)
        result = None
        if row.status == "completed" and row.final_output:
            try:
                result = json.loads(row.final_output)
            except ValueError:
                pass
        return {"run_id": row.id, "status": row.status, "result": result,
                "artifacts": artifact_store.list_artifacts(run_id)}


class ReaderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    task_id: str | None = Field(default=None, max_length=200)


async def _reader_scope(conversation_id: str, task_id: str | None):
    if task_id is not None:
        from server.db.models import CompanionTask
        async with db_session.AsyncSessionLocal() as db:
            task = await db.get(CompanionTask, task_id)
            if task is None or task.owner_id != "local" or task.conversation_id != conversation_id:
                raise HTTPException(404, detail={"code": "browser.task_not_found"})
            if task.cancel_requested or task.phase == "cancelled":
                await browser_reader.cancel_task(task_id)
                raise HTTPException(409, detail={"code": "browser.session_closed"})


@router.post("/browser/sessions", status_code=201)
async def reader_create(body: ReaderCreate):
    await _reader_scope(body.conversation_id, body.task_id)
    try:
        session = await browser_reader.create(body.conversation_id, body.task_id)
    except browser_reader.ReaderError as exc:
        raise HTTPException(409, detail={"code": exc.code}) from None
    except (OSError, ValueError, TimeoutError):
        raise HTTPException(503, detail={"code": "browser.runtime_failed"}) from None
    return {"session_id": session.id, "conversation_id": session.conversation_id, "task_id": session.task_id,
            "mode": "isolated_read_only"}


@router.post("/browser/sessions/{session_id}/actions")
async def reader_action(session_id: str, body: browser_reader.ReaderAction):
    session = browser_reader.sessions.get(session_id)
    if session is None or session.owner_id != "local":
        raise HTTPException(404, detail={"code": "browser.session_closed"})
    await _reader_scope(session.conversation_id, session.task_id)
    try:
        return await session.act(body)
    except browser_reader.ReaderError as exc:
        raise HTTPException(409, detail={"code": exc.code}) from None


@router.delete("/browser/sessions/{session_id}", status_code=204)
async def reader_close(session_id: str):
    session = browser_reader.sessions.get(session_id)
    if session is not None and session.owner_id == "local":
        await session.close()
        browser_reader.sessions.pop(session_id, None)


async def shutdown():
    tasks = list(_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await browser_reader.shutdown()
