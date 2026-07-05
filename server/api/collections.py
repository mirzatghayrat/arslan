"""Shared knowledge collections (layer A): CRUD, ingest, sources, spawn binding.
Ingest mirrors the per-spawn knowledge endpoint (JSON text/url or multipart)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy import text as sa_text

from server.auth import require_auth
from server.db import session as db_session
from server.db.models import Collection, SpawnCollection
from server.schemas import CollectionIn, CollectionOut, CollectionPatch, IngestOut, KnowledgeIn, KnowledgeSourceOut
from server.services import ingest

router = APIRouter(dependencies=[Depends(require_auth)])


async def _get_or_404(db, collection_id: int) -> Collection:
    row = await db.get(Collection, collection_id)
    if row is None:
        raise HTTPException(status_code=404, detail="collection not found")
    return row


@router.post("/collections", response_model=CollectionOut)
async def create_collection(body: CollectionIn) -> CollectionOut:
    async with db_session.AsyncSessionLocal() as db:
        row = Collection(name=body.name, description=body.description)
        db.add(row)
        await db.commit()
        return CollectionOut(id=row.id, name=row.name, description=row.description)


@router.get("/collections", response_model=list[CollectionOut])
async def list_collections() -> list[CollectionOut]:
    async with db_session.AsyncSessionLocal() as db:
        colls = (await db.execute(sa_text(
            "SELECT c.id, c.name, c.description FROM collections c ORDER BY c.id"))).all()
        stats = {r[0]: (r[1], r[2]) for r in (await db.execute(sa_text(
            "SELECT collection_id, COUNT(*), COUNT(DISTINCT source) FROM knowledge_chunks "
            "WHERE collection_id IS NOT NULL GROUP BY collection_id"))).all()}
        binds: dict[int, list[int]] = {}
        for cid, sid in (await db.execute(sa_text(
                "SELECT collection_id, spawn_id FROM spawn_collections ORDER BY spawn_id"))).all():
            binds.setdefault(cid, []).append(sid)
        return [CollectionOut(id=c[0], name=c[1], description=c[2],
                              chunks=stats.get(c[0], (0, 0))[0],
                              sources=stats.get(c[0], (0, 0))[1],
                              spawn_ids=binds.get(c[0], []))
                for c in colls]


@router.patch("/collections/{collection_id}", response_model=CollectionOut)
async def patch_collection(collection_id: int, body: CollectionPatch) -> CollectionOut:
    async with db_session.AsyncSessionLocal() as db:
        row = await _get_or_404(db, collection_id)
        if body.name is not None:
            row.name = body.name
        if body.description is not None:
            row.description = body.description
        await db.commit()
        return CollectionOut(id=row.id, name=row.name, description=row.description)


async def _delete_fts_for(db, ids: list[int]) -> None:
    for rid in ids:
        await db.execute(sa_text("DELETE FROM knowledge_chunks_fts WHERE rowid = :rid"), {"rid": rid})


@router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: int) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        row = await _get_or_404(db, collection_id)
        ids = [r[0] for r in (await db.execute(sa_text(
            "SELECT id FROM knowledge_chunks WHERE collection_id = :cid"),
            {"cid": collection_id})).all()]
        await _delete_fts_for(db, ids)
        # Explicit delete rather than relying on ON DELETE CASCADE: SQLite defaults
        # foreign_keys=OFF and this engine does not opt in, so cascade would not fire.
        await db.execute(sa_text(
            "DELETE FROM knowledge_chunks WHERE collection_id = :cid"), {"cid": collection_id})
        await db.execute(sa_text(
            "DELETE FROM spawn_collections WHERE collection_id = :cid"), {"cid": collection_id})
        await db.delete(row)
        await db.commit()
    return {"deleted": True, "chunks_removed": len(ids)}


@router.post("/collections/{collection_id}/ingest", response_model=IngestOut)
async def ingest_collection(collection_id: int, request: Request) -> IngestOut:
    """Mirror of the per-spawn knowledge ingest: JSON {text}|{url} or multipart file."""
    async with db_session.AsyncSessionLocal() as db:
        await _get_or_404(db, collection_id)
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        file: UploadFile | None = form.get("file")  # type: ignore[assignment]
        if file is None:
            raise HTTPException(status_code=400, detail="provide a 'file' field in the form")
        data = await file.read()
        compress = str(form.get("compress", "")).lower() in ("1", "true", "yes")
        try:
            n = await ingest.ingest_file(None, file.filename or "upload", data,
                                         collection_id=collection_id, compress=compress)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"could not parse file: {exc}") from exc
        return IngestOut(source=file.filename or "upload", chunks_added=n)
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="provide JSON {source, text} or a file upload") from exc
    try:
        body = KnowledgeIn(**payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.url:
        try:
            n = await ingest.ingest_url(None, body.url, collection_id=collection_id, compress=body.compress)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return IngestOut(source=body.url, chunks_added=n)
    if body.text:
        n = await ingest.ingest_text(None, body.source or "text", body.text,
                                     collection_id=collection_id, compress=body.compress)
        return IngestOut(source=body.source or "text", chunks_added=n)
    raise HTTPException(status_code=400, detail="provide url, text, or a file")


@router.get("/collections/{collection_id}/knowledge", response_model=list[KnowledgeSourceOut])
async def list_collection_knowledge(collection_id: int) -> list[KnowledgeSourceOut]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(sa_text(
            "SELECT source, COUNT(*) FROM knowledge_chunks "
            "WHERE collection_id = :cid GROUP BY source"), {"cid": collection_id})
        return [KnowledgeSourceOut(source=r[0], chunks=r[1]) for r in rows.all()]


@router.delete("/collections/{collection_id}/knowledge")
async def delete_collection_source(collection_id: int, source: str) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        ids = [r[0] for r in (await db.execute(sa_text(
            "SELECT id FROM knowledge_chunks WHERE collection_id = :cid AND source = :src"),
            {"cid": collection_id, "src": source})).all()]
        await _delete_fts_for(db, ids)
        await db.execute(sa_text(
            "DELETE FROM knowledge_chunks WHERE collection_id = :cid AND source = :src"),
            {"cid": collection_id, "src": source})
        await db.commit()
    return {"deleted": len(ids)}


@router.put("/spawns/{spawn_id}/collections/{collection_id}")
async def bind_collection(spawn_id: int, collection_id: int) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        await _get_or_404(db, collection_id)
        exists = (await db.execute(sa_text(
            "SELECT 1 FROM spawn_collections WHERE spawn_id = :sid AND collection_id = :cid"),
            {"sid": spawn_id, "cid": collection_id})).first()
        if not exists:
            db.add(SpawnCollection(spawn_id=spawn_id, collection_id=collection_id))
            await db.commit()
    return {"bound": True}


@router.delete("/spawns/{spawn_id}/collections/{collection_id}")
async def unbind_collection(spawn_id: int, collection_id: int) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(sa_text(
            "DELETE FROM spawn_collections WHERE spawn_id = :sid AND collection_id = :cid"),
            {"sid": spawn_id, "cid": collection_id})
        await db.commit()
    return {"bound": False}
