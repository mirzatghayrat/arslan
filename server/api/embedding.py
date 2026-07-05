"""Embedding ops: current provider status, backfill trigger, local model download."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import text as sa_text

from server.auth import require_auth
from server.db import session as db_session
from server.services import embedding_service, local_embedding

router = APIRouter(dependencies=[Depends(require_auth)])

# Hold strong refs to fire-and-forget tasks: asyncio keeps only a weak ref to a
# running Task, so a bare create_task(...) whose return value is discarded can be
# garbage-collected mid-flight, silently killing the backfill/download. The
# done-callback discards the ref once the task settles, so the set never grows.
_bg_tasks: set[asyncio.Task] = set()


def _fire(coro) -> None:
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)


@router.get("/embedding/status")
async def embedding_status() -> dict:
    provider = await embedding_service.active_provider()
    async with db_session.AsyncSessionLocal() as db:
        embedded = (await db.execute(sa_text(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL"))).scalar_one()
        total = (await db.execute(sa_text(
            "SELECT COUNT(*) FROM knowledge_chunks"))).scalar_one()
    # With an active provider, 'pending' is the real embed_missing() backlog
    # (NULL or stale-model) so a model switch honestly shows work remaining;
    # without one, it's rows lacking any vector at all.
    pending = (
        await embedding_service.pending_count(provider.model_id)
        if provider else total - embedded
    )
    return {
        "provider": type(provider).__name__ if provider else None,
        "model": provider.model_id if provider else None,
        "embedded": embedded,
        "pending": pending,
        "reindex": embedding_service.reindex_status(),
        "local_model": local_embedding.download_status(),
    }


@router.post("/embedding/reindex")
async def trigger_reindex() -> dict:
    provider = await embedding_service.active_provider()
    if provider is None:
        return {"started": False, "reason": "no embedding provider configured"}
    _fire(embedding_service.embed_missing())
    return {"started": True}


@router.post("/embedding/download-model")
async def trigger_download() -> dict:
    _fire(local_embedding.download_local_model())
    return {"started": True, "status": local_embedding.download_status()}
