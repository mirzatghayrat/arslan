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


async def shutdown():
    tasks = list(_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
