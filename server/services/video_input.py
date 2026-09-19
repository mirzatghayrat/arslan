"""Bounded local video sampling; no model calls, audio transcription or editing."""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

from server.services.input_formats import primary_video_stream, video_metadata

FRAME_COUNT = 3
MAX_EDGE = 512
MAX_FRAME_BYTES = 2 * 1024 * 1024


def extract_video(filename: str, data: bytes) -> dict:
    report = video_metadata(filename, data)
    stream = primary_video_stream(report["metadata"])
    images: list[dict] = []
    frames: list[dict] = []
    status = "tool_missing"
    executable = shutil.which("ffmpeg")
    if executable:
        status = "time_unavailable"
        try:
            duration = float(report["metadata"].get("format", {}).get("duration", 0))
        except (ValueError, TypeError):
            duration = 0
        try:
            width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
        except (ValueError, TypeError):
            width = height = 0
        if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 25_000_000):
            status = "invalid_dimensions"
        elif math.isfinite(duration) and 0 < duration <= 86400:
            status = "decode_failed"
            with tempfile.TemporaryDirectory(prefix="arslan-frames-") as folder:
                source = Path(folder) / ("input" + Path(filename).suffix.lower())
                source.write_bytes(data)
                for index, fraction in enumerate((0, 0.5, 0.9)):
                    timestamp = round(duration * fraction, 3)
                    target = Path(folder) / f"frame-{index}.png"
                    try:
                        result = subprocess.run([
                            executable, "-nostdin", "-hide_banner", "-v", "error", "-y",
                            "-max_alloc", "67108864", "-threads", "1",
                            "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm",
                            "-ss", str(timestamp), "-i", str(source), "-map", f"0:{stream['index']}",
                            "-an", "-sn", "-dn", "-frames:v", "1",
                            "-vf", f"scale={MAX_EDGE}:{MAX_EDGE}:force_original_aspect_ratio=decrease",
                            "-threads", "1", "-f", "image2", str(target),
                        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=8, cwd=folder,
                            env={"PATH": "/usr/bin:/bin", "HOME": folder, "TMPDIR": folder})
                        if result.returncode or not target.is_file() or not 0 < target.stat().st_size <= MAX_FRAME_BYTES:
                            break
                        raw = target.read_bytes()
                        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                            break
                        name = f"{filename}#t={timestamp:.3f}s"
                        images.append({"name": name, "source_locator": name, "mime_type": "image/png", "data": base64.b64encode(raw).decode("ascii")})
                        frames.append({"name": name, "seek_time_seconds": timestamp})
                    except (OSError, subprocess.TimeoutExpired):
                        break
            if images:
                status = "sampled" if len(images) == FRAME_COUNT else "partial"
    report.update({"frames": frames, "frame_status": status,
                   "sampled_video_stream_index": stream["index"] if images else None,
                   "sampling": "Only the first non-cover video stream is sampled, up to three still frames at 0%, 50%, 90%; seek times are approximate. Other streams and unsampled content are not analyzed.",
                   "transcript": "unavailable_no_transcription_adapter",
                   "visual_understanding": "requires_selected_vision_model" if images else "not_run"})
    text = json.dumps(report, ensure_ascii=False, indent=2)
    return {"text": text, "chars": len(text), "truncated": False, "input_kind": "video",
            "images": images, "video_frame_status": status, "video_transcription": False}
