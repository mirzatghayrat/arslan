"""Extract text from a file/URL WITHOUT storing it (ephemeral attachments).

Reuses the same extraction internals as ingest (OCR-capable file parse) and the
SSRF-guarded web fetch executor. Caps output to a configurable limit."""
from __future__ import annotations

from server.config import settings
from server.services import ingest


async def extract_text(
    *, filename: str | None = None, data: bytes | None = None,
    url: str | None = None, compress: bool = False,
) -> tuple[str, bool]:
    """Return (text, truncated). Raises ValueError on fetch failure / private URL."""
    if url:
        # 🔒 SSRF: only via the guarded WebExtractExecutor (per-hop host revalidation).
        from server.registry.executors import EXECUTORS
        res = await EXECUTORS["web_extract"].execute({"url": url})
        if not res.get("ok"):
            raise ValueError(res.get("error") or "fetch failed")
        text = res.get("text", "")
    elif data is not None:
        text = ingest._extract_file(filename or "file", data)
    else:
        raise ValueError("provide url or file data")

    if compress:
        text = await ingest._compress(text)

    limit = settings.attach_extract_char_limit
    if len(text) > limit:
        return text[:limit], True
    return text, False
