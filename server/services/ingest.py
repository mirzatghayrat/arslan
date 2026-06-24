"""Ingest material into a spawn's knowledge base: extract text (files), strip
<private> blocks, chunk, and store to knowledge_chunks + FTS5."""
from __future__ import annotations

import io
import logging
import re

from sqlalchemy import text as sa_text

from arslan.core.chunking import chunk_text
from server.db import session as db_session
from server.db.models import KnowledgeChunk
from server.services.llm_factory import build_adapter
from server.services.prompts.kb_compress import COMPRESS_SYSTEM

logger = logging.getLogger(__name__)

_PRIVATE_RE = re.compile(r"<private>.*?</private>", re.DOTALL | re.IGNORECASE)
_OCR_MIN_CHARS = 20


def _strip_private(text: str) -> str:
    return _PRIVATE_RE.sub("", text or "")


def _pdf_text_layer(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _ocr_pdf(data: bytes) -> str:
    """OCR a scanned PDF (no text layer). Best-effort; returns '' on any failure."""
    try:
        import fitz  # pymupdf
        import pytesseract
        from PIL import Image
        out = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                try:
                    out.append(pytesseract.image_to_string(img, lang="chi_sim+eng"))
                except Exception:  # noqa: BLE001 — language pack missing → English only
                    out.append(pytesseract.image_to_string(img))
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001 — OCR is best-effort
        logger.warning("OCR failed: %s", exc)
        return ""


def _extract_file(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".txt") or name.endswith(".md"):
        return data.decode("utf-8", errors="replace")
    if name.endswith(".pdf"):
        text = _pdf_text_layer(data)
        if len(text.strip()) < _OCR_MIN_CHARS:
            try:
                ocr = _ocr_pdf(data)
            except Exception as exc:  # noqa: BLE001 — defense in depth (stubbed _ocr_pdf may raise)
                logger.warning("OCR fallback errored: %s", exc)
                ocr = ""
            if ocr.strip():
                return ocr
        return text
    if name.endswith(".docx"):
        import docx  # python-docx
        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)
    raise ValueError(f"unsupported file type: {filename}")


async def _compress(text: str) -> str:
    """LLM-clean text; best-effort — returns original on failure/empty."""
    try:
        adapter = await build_adapter(role="converse")
        resp = await adapter.chat(system=COMPRESS_SYSTEM, user=text)
        cleaned = (resp.content or "").strip()
        return cleaned if cleaned else text
    except Exception as exc:  # noqa: BLE001
        logger.warning("kb compress failed, using original: %s", exc)
        return text


async def ingest_text(spawn_id: int, source: str, text: str, *, compress: bool = False) -> int:
    """Strip private blocks, chunk, store. Returns number of chunks stored."""
    cleaned = _strip_private(text)
    if compress:
        cleaned = await _compress(cleaned)
    chunks = chunk_text(cleaned)
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


async def ingest_url(spawn_id: int, url: str, *, compress: bool = False) -> int:
    """Fetch + extract a web page via the SSRF-guarded WebExtractExecutor (per-hop
    host revalidation + private-IP block — NEVER a raw httpx request), then ingest.
    Raises ValueError on fetch failure / private-address rejection."""
    from server.registry.executors import EXECUTORS
    res = await EXECUTORS["web_extract"].execute({"url": url})
    if not res.get("ok"):
        raise ValueError(res.get("error") or "fetch failed")
    return await ingest_text(spawn_id, url, res.get("text", ""), compress=compress)


async def ingest_file(spawn_id: int, filename: str, data: bytes) -> int:
    """Extract text from a supported file then ingest. Raises ValueError on
    unsupported extension; extraction errors propagate (API maps to 400)."""
    extracted = _extract_file(filename, data)
    return await ingest_text(spawn_id, filename, extracted)
