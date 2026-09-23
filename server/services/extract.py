"""Extract text from a file/URL WITHOUT storing it (ephemeral attachments).

Reuses the same extraction internals as ingest (OCR-capable file parse) and the
SSRF-guarded web fetch executor. Caps output to a configurable limit."""
from __future__ import annotations

from server.config import settings
from server.services import ingest
from server.services.input_formats import kind, read_structured, video_metadata


def _pdf_inventory(text: str, layer: ingest.PDFTextLayer) -> str:
    """Keep physical-page existence distinct from extracted text availability.

    This is parser metadata, never an OCR/visual claim or document quotation.
    Empty extraction stays empty so metadata alone cannot masquerade as content.
    A bounded list avoids unbounded prompt overhead on sparse, long documents.
    """
    if not text.strip():
        return text
    import json
    no_text = [index for index, page in enumerate(layer.pages, 1) if not page.strip()]
    metadata = {
        "page_count": len(layer.pages),
        "page_numbers": "one_based_physical_pages",
        "pages_without_native_text": no_text[:64],
        "pages_without_native_text_count": len(no_text),
        "page_list_truncated": len(no_text) > 64,
        "empty_text_is_not_missing_page": True,
        "visual_layout_verified": False,
        "note": "All physical pages exist in the parsed PDF. Missing native text is not proof of blankness, "
                "a missing page, or an incomplete document. OCR results and unread-page notices below "
                "are separate; this inventory does not certify that all page content was read.",
    }
    return ("[PDF extraction inventory; not document content]\n"
            + json.dumps(metadata, ensure_ascii=False) + "\n\n" + text)


async def extract_text(
    *, filename: str | None = None, data: bytes | None = None,
    url: str | None = None, compress: bool = False,
) -> tuple[str, bool]:
    """Return (text, truncated). Raises ValueError on fetch failure / private URL."""
    source_truncated = False
    preserve_source = False
    if url:
        # 🔒 SSRF: only via the guarded WebExtractExecutor (per-hop host revalidation).
        from server.registry.executors import EXECUTORS
        res = await EXECUTORS["web_extract"].execute({"url": url})
        if not res.get("ok"):
            raise ValueError(res.get("error") or "fetch failed")
        text = res.get("text", "")
    elif data is not None:
        # The locale is read here, once, from the same helper the brain-feed
        # route uses — two readers would eventually ask Vision for different
        # languages on the same file depending on which door it came through.
        from server.services import ocr_fallback

        category = kind(filename or "")
        if ((category in {"text", "spreadsheet", "presentation"} and not (filename or "").lower().endswith((".txt", ".md")))
                or (filename or "").lower().endswith(".docx")):
            import asyncio
            text, source_truncated = await asyncio.to_thread(read_structured, filename or "file", data)
            preserve_source = True
        elif category == "video":
            import asyncio
            import json
            text = json.dumps(await asyncio.to_thread(video_metadata, filename or "file", data), ensure_ascii=False, indent=2)
            preserve_source = True
        elif (filename or "").lower().endswith(".pdf"):
            import asyncio
            language = await ocr_fallback.current_ui_language()
            languages = await ocr_fallback.current_ocr_languages()
            layer = await asyncio.to_thread(ingest._pdf_text_layer, data)
            if layer.has_text and layer.ocr_pages:
                text, source_truncated = await asyncio.to_thread(
                    ingest._mixed_pdf_text, data, layer, language, languages)
            else:
                text = await asyncio.to_thread(ingest._extract_file,
                    filename or "file.pdf", data, ui_language=language,
                    ocr_languages=languages)
            text = _pdf_inventory(text, layer)
            preserve_source = True
        else:
            text = ingest._extract_file(
                filename or "file", data,
                ui_language=await ocr_fallback.current_ui_language(),
                ocr_languages=await ocr_fallback.current_ocr_languages())
    else:
        raise ValueError("provide url or file data")

    # Source locators, formula metadata and code are evidence, not prose for a
    # cleanup model to rewrite. Keep legacy opt-in prose/URL cleanup separate.
    preserve_source |= data is not None and (filename or "").lower().endswith(".pdf")
    if compress and not preserve_source:
        text = await ingest._compress(text)

    limit = settings.attach_extract_char_limit
    if len(text) > limit:
        return text[:limit], True
    return text, source_truncated
