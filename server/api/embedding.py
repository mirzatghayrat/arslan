"""Embedding ops: current provider status, backfill trigger, local model download."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import text as sa_text

from server.auth import require_auth
from server.db import session as db_session
from server.services import embedding_service, local_embedding

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/embedding/status")
async def embedding_status() -> dict:
    provider = await embedding_service.active_provider()
    async with db_session.AsyncSessionLocal() as db:
        embedded = (await db.execute(sa_text(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL"))).scalar_one()
        total = (await db.execute(sa_text(
            "SELECT COUNT(*) FROM knowledge_chunks"))).scalar_one()
    return {
        "provider": type(provider).__name__ if provider else None,
        "model": provider.model_id if provider else None,
        "embedded": embedded,
        "pending": total - embedded,
        "reindex": embedding_service.reindex_status(),
        "local_model": local_embedding.download_status(),
    }


@router.post("/embedding/reindex")
async def trigger_reindex() -> dict:
    provider = await embedding_service.active_provider()
    if provider is None:
        return {"started": False, "reason": "no embedding provider configured"}
    asyncio.create_task(embedding_service.embed_missing())
    return {"started": True}


@router.post("/embedding/download-model")
async def trigger_download() -> dict:
    asyncio.create_task(local_embedding.download_local_model())
    return {"started": True, "status": local_embedding.download_status()}
