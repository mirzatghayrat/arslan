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
_IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif)$", re.IGNORECASE)


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


def _ocr_image(data: bytes) -> str:
    """OCR a standalone image attachment. Best-effort; returns '' on any failure
    (undecodable bytes, missing tesseract) or when no text is found. convert("RGB")
    normalizes RGBA/palette modes and takes an animated GIF's first frame."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        try:
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        except Exception:  # noqa: BLE001 — language pack missing → English only
            text = pytesseract.image_to_string(img)
        return text if text.strip() else ""
    except Exception as exc:  # noqa: BLE001 — OCR is best-effort
        logger.warning("image OCR failed: %s", exc)
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
    if _IMAGE_EXT_RE.search(name):
        # No text found / OCR unavailable → '' (caller surfaces "no text", never 500).
        return _ocr_image(data)
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


async def ingest_text(spawn_id: int | None, source: str, text: str, *,
                      collection_id: int | None = None, compress: bool = False) -> int:
    """Strip private blocks, chunk, store into EXACTLY ONE of a spawn's private
    well (spawn_id) or a shared collection (collection_id), then best-effort
    embed the new chunks. Returns number of chunks stored."""
    if (spawn_id is None) == (collection_id is None):
        raise ValueError("provide exactly one of spawn_id / collection_id")
    cleaned = _strip_private(text)
    if compress:
        cleaned = await _compress(cleaned)
    chunks = chunk_text(cleaned)
    if not chunks:
        return 0
    ids_texts: list[tuple[int, str]] = []
    async with db_session.AsyncSessionLocal() as db:
        for i, chunk in enumerate(chunks):
            row = KnowledgeChunk(spawn_id=spawn_id, collection_id=collection_id,
                                 source=source, chunk_index=i, text=chunk)
            db.add(row)
            await db.flush()  # populate row.id for the FTS rowid
            # Defensive: clear any stale FTS row at this rowid first. knowledge_chunks
            # ids restart from 1 when the table is emptied, so a leftover FTS orphan
            # (from a crash / partial delete / migration edge) would otherwise collide
            # and 500 every ingest. Delete-then-insert keeps the FTS mirror consistent.
            await db.execute(
                sa_text("DELETE FROM knowledge_chunks_fts WHERE rowid = :rid"),
                {"rid": row.id},
            )
            await db.execute(
                sa_text("INSERT INTO knowledge_chunks_fts (rowid, text) VALUES (:rid, :t)"),
                {"rid": row.id, "t": chunk},
            )
            ids_texts.append((row.id, chunk))
        await db.commit()
    await _embed_new_chunks(ids_texts)
    return len(chunks)


async def _embed_new_chunks(ids_texts: list[tuple[int, str]]) -> None:
    """Vectorize freshly stored chunks. Best-effort: any failure leaves the
    embedding NULL and the chunks retrievable via FTS only. All chunks from one
    ingest are sent as a single un-chunked provider batch, so an oversized
    input can fail the whole batch at once; recovery relies on the
    embed_missing() backfill picking up the resulting NULL rows later."""
    if not ids_texts:
        return
    try:
        from server.services import embedding_service
        provider = await embedding_service.active_provider()
        if provider is None:
            return
        vecs = await provider.embed([t for _, t in ids_texts])
        async with db_session.AsyncSessionLocal() as db:
            for (cid, _), vec in zip(ids_texts, vecs):
                await db.execute(
                    sa_text("UPDATE knowledge_chunks SET embedding = :b, embedding_model = :m "
                            "WHERE id = :id"),
                    {"b": embedding_service.vec_to_blob(vec), "m": provider.model_id, "id": cid},
                )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — embedding is never fatal
        logger.warning("chunk embedding failed (non-fatal, FTS-only): %s", exc)


async def ingest_url(spawn_id: int | None, url: str, *,
                     collection_id: int | None = None, compress: bool = False) -> int:
    """Fetch + extract a web page via the SSRF-guarded WebExtractExecutor (per-hop
    host revalidation + private-IP block — NEVER a raw httpx request), then ingest.
    Raises ValueError on fetch failure / private-address rejection."""
    from server.registry.executors import EXECUTORS
    res = await EXECUTORS["web_extract"].execute({"url": url})
    if not res.get("ok"):
        raise ValueError(res.get("error") or "fetch failed")
    return await ingest_text(spawn_id, url, res.get("text", ""),
                             collection_id=collection_id, compress=compress)


async def ingest_file(spawn_id: int | None, filename: str, data: bytes, *,
                      collection_id: int | None = None, compress: bool = False) -> int:
    """Extract text from a supported file then ingest. Raises ValueError on
    unsupported extension; extraction errors propagate (API maps to 400)."""
    extracted = _extract_file(filename, data)
    return await ingest_text(spawn_id, filename, extracted,
                             collection_id=collection_id, compress=compress)
