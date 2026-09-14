"""Extract text from a file/URL WITHOUT storing it (ephemeral attachments).

Reuses the same extraction internals as ingest (OCR-capable file parse) and the
SSRF-guarded web fetch executor. Caps output to a configurable limit."""
from __future__ import annotations

from server.config import settings
from server.services import ingest
from server.services.input_formats import kind, read_structured, video_metadata


async def extract_text(
    *, filename: str | None = None, data: bytes | None = None,
    url: str | None = None, compress: bool = False,
) -> tuple[str, bool]:
    """Return (text, truncated). Raises ValueError on fetch failure / private URL."""
    source_truncated = False
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
        if category in {"text", "spreadsheet", "presentation"} and not (filename or "").lower().endswith((".txt", ".md")):
            import asyncio
            text, source_truncated = await asyncio.to_thread(read_structured, filename or "file", data)
        elif category == "video":
            import asyncio
            import json
            text = json.dumps(await asyncio.to_thread(video_metadata, filename or "file", data), ensure_ascii=False, indent=2)
        else:
            text = ingest._extract_file(
                filename or "file", data,
                ui_language=await ocr_fallback.current_ui_language(),
                ocr_languages=await ocr_fallback.current_ocr_languages())
    else:
        raise ValueError("provide url or file data")

    if compress:
        text = await ingest._compress(text)

    limit = settings.attach_extract_char_limit
    if len(text) > limit:
        return text[:limit], True
    return text, source_truncated
