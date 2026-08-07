"""POST /extract — extract text from a file/URL without storing (ephemeral)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from server.api.media_type import is_multipart_form
from server.auth import require_auth
from server.services import extract

router = APIRouter(prefix="/api/v1", tags=["extract"], dependencies=[Depends(require_auth)])


@router.post("/extract")
async def post_extract(request: Request) -> dict:
    try:
        # Ask the question the way Starlette's form parser answers it — a substring
        # test on the raw header disagrees with it (see server/api/media_type.py).
        if is_multipart_form(request.headers.get("content-type", "")):
            form = await request.form()
            upload = form.get("file")
            if upload is None:
                raise HTTPException(400, "file required")
            data = await upload.read()
            compress = str(form.get("compress", "")).lower() in ("1", "true", "yes")
            text, truncated = await extract.extract_text(
                filename=upload.filename, data=data, compress=compress
            )
        else:
            body = await request.json()
            url = (body.get("url") or "").strip()
            if not url:
                raise HTTPException(400, "provide url or a file")
            text, truncated = await extract.extract_text(
                url=url, compress=bool(body.get("compress"))
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"text": text, "chars": len(text), "truncated": truncated}
