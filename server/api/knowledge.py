"""Per-spawn knowledge base: ingest (text or file), list sources, delete a source."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sqlalchemy import text as sa_text

from server.auth import require_auth
from server.db import session as db_session
from server.schemas import IngestOut, KnowledgeIn, KnowledgeSourceOut
from server.services import ingest

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/spawns/{spawn_id}/knowledge", response_model=IngestOut)
async def add_knowledge(spawn_id: int, request: Request) -> IngestOut:
    """Accept either JSON {source, text} or a multipart file upload."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        file: UploadFile | None = form.get("file")  # type: ignore[assignment]
        if file is None:
            raise HTTPException(status_code=400, detail="provide a 'file' field in the form")
        data = await file.read()
        try:
            n = await ingest.ingest_file(spawn_id, file.filename or "upload", data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"could not parse file: {exc}") from exc
        return IngestOut(source=file.filename or "upload", chunks_added=n)

    # Fall through to JSON body
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="provide JSON {source, text} or a file upload") from exc
    try:
        body = KnowledgeIn(**payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    n = await ingest.ingest_text(spawn_id, body.source, body.text)
    return IngestOut(source=body.source, chunks_added=n)


@router.get("/spawns/{spawn_id}/knowledge", response_model=list[KnowledgeSourceOut])
async def list_knowledge(spawn_id: int) -> list[KnowledgeSourceOut]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            sa_text(
                "SELECT source, COUNT(*) AS n FROM knowledge_chunks "
                "WHERE spawn_id = :sid GROUP BY source"
            ),
            {"sid": spawn_id},
        )
        return [KnowledgeSourceOut(source=r[0], chunks=r[1]) for r in rows.all()]


@router.delete("/spawns/{spawn_id}/knowledge")
async def delete_knowledge(spawn_id: int, source: str) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        ids = [
            r[0]
            for r in (
                await db.execute(
                    sa_text(
                        "SELECT id FROM knowledge_chunks WHERE spawn_id = :sid AND source = :src"
                    ),
                    {"sid": spawn_id, "src": source},
                )
            ).all()
        ]
        for rid in ids:
            await db.execute(
                sa_text("DELETE FROM knowledge_chunks_fts WHERE rowid = :rid"), {"rid": rid}
            )
        await db.execute(
            sa_text(
                "DELETE FROM knowledge_chunks WHERE spawn_id = :sid AND source = :src"
            ),
            {"sid": spawn_id, "src": source},
        )
        await db.commit()
    return {"deleted": len(ids)}
