"""POST /extract — extract text from a file/URL without storing (ephemeral)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from server.api.media_type import is_multipart_form
from server.auth import require_auth
from server.services import extract
from server.services.input_formats import REGISTRY, InputError, kind

router = APIRouter(prefix="/api/v1", tags=["extract"], dependencies=[Depends(require_auth)])


@router.get("/input-formats")
async def input_formats() -> dict:
    import shutil
    return {**REGISTRY, "video_metadata_available": bool(shutil.which("ffprobe")),
            "video_frames": bool(shutil.which("ffprobe") and shutil.which("ffmpeg")),
            "video_transcription": False, "video_transcription_reason": "no_transcription_adapter",
            "video_visual_understanding": False, "video_visual_mode": "sampled_frames_require_vision_model",
            "spreadsheet_formulas": "cached_values_only", "presentation": REGISTRY["presentation"],
            "presentation_visual_understanding": False}


@router.post("/extract")
async def post_extract(request: Request) -> dict:
    category = None
    try:
        # Ask the question the way Starlette's form parser answers it — a substring
        # test on the raw header disagrees with it (see server/api/media_type.py).
        if is_multipart_form(request.headers.get("content-type", "")):
            form = await request.form()
            upload = form.get("file")
            if upload is None:
                raise HTTPException(400, "file required")
            data = await upload.read(REGISTRY["max_bytes"] + 1)
            if len(data) > REGISTRY["max_bytes"]:
                raise InputError("inputs.limit")
            category = kind(upload.filename or "")
            if category == "video":
                import asyncio
                from server.services.video_input import extract_video
                return await asyncio.to_thread(extract_video, upload.filename or "video", data)
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
    except InputError as exc:
        raise HTTPException(400, {"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"text": text, "chars": len(text), "truncated": truncated, "input_kind": category}
