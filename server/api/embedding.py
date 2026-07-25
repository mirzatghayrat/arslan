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
        # Which model each existing vector came from. Switching the embedding provider
        # does NOT re-embed anything (update_settings has no embedding side effect, by
        # design — re-embedding spends money and must be the user's explicit choice), so
        # a switch leaves the corpus split across two vector spaces whose distances are
        # not comparable. Without this the UI could warn that it MIGHT happen but never
        # say whether it already had; the column exists, the count was simply never read.
        by_model = [
            {"model": row[0], "count": row[1]}
            for row in (await db.execute(sa_text(
                "SELECT embedding_model, COUNT(*) FROM knowledge_chunks "
                "WHERE embedding IS NOT NULL GROUP BY embedding_model "
                "ORDER BY COUNT(*) DESC"))).all()
        ]
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
        # 🔴 `embedded + pending` is NOT the corpus size and never was: with a provider
        # active, `pending` counts NULL-or-STALE rows, and a stale row is also counted in
        # `embedded` (it does have a vector, just the wrong model's). So after a model
        # switch the sum exceeds the real total and any progress bar built on it reads
        # about half of true progress. The corpus size was already computed here and
        # simply never returned; a client cannot derive it.
        "total": total,
        # [{model, count}] over rows that HAVE a vector. More than one entry means the
        # corpus is split across models; empty means nothing is embedded at all.
        "by_model": by_model,
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
