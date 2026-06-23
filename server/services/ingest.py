"""Ingest material into a spawn's knowledge base: extract text (files), strip
<private> blocks, chunk, and store to knowledge_chunks + FTS5."""
from __future__ import annotations

import io
import re

from sqlalchemy import text as sa_text

from arslan.core.chunking import chunk_text
from server.db import session as db_session
from server.db.models import KnowledgeChunk

_PRIVATE_RE = re.compile(r"<private>.*?</private>", re.DOTALL | re.IGNORECASE)


def _strip_private(text: str) -> str:
    return _PRIVATE_RE.sub("", text or "")


def _extract_file(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".txt") or name.endswith(".md"):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if name.endswith(".docx"):
        import docx  # python-docx
        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)
    raise ValueError(f"unsupported file type: {filename}")


async def ingest_text(spawn_id: int, source: str, text: str) -> int:
    """Strip private blocks, chunk, store. Returns number of chunks stored."""
    chunks = chunk_text(_strip_private(text))
    if not chunks:
        return 0
    async with db_session.AsyncSessionLocal() as db:
        for i, chunk in enumerate(chunks):
            row = KnowledgeChunk(spawn_id=spawn_id, source=source, chunk_index=i, text=chunk)
            db.add(row)
            await db.flush()  # populate row.id for the FTS rowid
            await db.execute(
                sa_text("INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (:rid, :t)"),
                {"rid": row.id, "t": chunk},
            )
        await db.commit()
    return len(chunks)


async def ingest_file(spawn_id: int, filename: str, data: bytes) -> int:
    """Extract text from a supported file then ingest. Raises ValueError on
    unsupported extension; extraction errors propagate (API maps to 400)."""
    extracted = _extract_file(filename, data)
    return await ingest_text(spawn_id, filename, extracted)
