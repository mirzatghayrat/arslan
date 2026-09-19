"""Local synthetic MP4 API acceptance for a temporary frozen candidate.

Uses already-installed FFmpeg tools, no downloads, user media or model calls.
Fixtures, application profile and owned process are removed on exit.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PIL import Image

from scripts.frozen_sidecar_smoke import start, stop


def fixture(folder: Path, ffmpeg: str, include_video: bool) -> Path:
    cover_image = folder / "cover.jpg"
    with Image.new("RGB", (32, 32), "red") as image:
        image.save(cover_image)
    target = folder / ("video-cover.mp4" if include_video else "cover-only.mp4")
    args = [ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
            "anullsrc=r=8000:cl=mono", "-i", str(cover_image)]
    if include_video:
        args += ["-f", "lavfi", "-i", "color=c=blue:size=64x48:rate=5"]
    args += ["-map", "0:a"]
    if include_video:
        args += ["-map", "2:v", "-c:v:0", "libx264"]
    cover = 1 if include_video else 0
    args += ["-map", "1:v", f"-c:v:{cover}", "copy",
             f"-disposition:v:{cover}", "attached_pic", "-c:a", "aac", "-t", "2", str(target)]
    subprocess.run(args, check=True, timeout=15, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   cwd=folder, env={"PATH": "/usr/bin:/bin", "HOME": str(folder), "TMPDIR": str(folder)})
    return target


def main() -> None:
    binary = Path(sys.argv[1]).resolve()
    assert binary.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert any(part.startswith(("arslan-candidate-build.", "arslan-native-candidate."))
               for part in binary.parts)
    assert binary.name == "arslan-server" and binary.is_file()
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    assert ffmpeg and ffprobe, "Existing local codec tools required; nothing is installed automatically"
    # Explicitly expose only the discovered tool directories, not the caller's
    # complete environment. The normal smoke retains its minimal default PATH.
    tool_path = ":".join(dict.fromkeys([str(Path(ffmpeg).parent), str(Path(ffprobe).parent),
                                      "/usr/bin", "/bin"]))
    with tempfile.TemporaryDirectory(prefix="arslan-frozen-video-") as folder:
        home = Path(folder)
        sources = [(include_video, fixture(home, ffmpeg, include_video))
                   for include_video in (False, True)]
        process, client, _ = start(binary, home, tool_path=tool_path)
        try:
            assert client.get("/api/v1/input-formats").json()["video_frames"] is True
            for include_video, source in sources:
                response = client.post("/api/v1/extract",
                    files={"file": (source.name, source.read_bytes(), "video/mp4")},
                    data={"compress": "true"}, timeout=60)
                if not include_video:
                    assert response.status_code == 400
                    assert response.json() == {"detail": {"code": "inputs.invalid"}}
                    continue
                assert response.status_code == 200
                result = response.json()
                report = json.loads(result["text"])
                assert result["video_frame_status"] == "sampled"
                assert len(result["images"]) == 3
                assert report["sampled_video_stream_index"] == 1
                assert any(s.get("disposition", {}).get("attached_pic") == 1
                           for s in report["metadata"]["streams"])
                assert report["transcript"] == "unavailable_no_transcription_adapter"
                for payload in result["images"]:
                    assert payload["source_locator"].startswith(source.name + "#t=")
                    with Image.open(io.BytesIO(base64.b64decode(payload["data"]))) as image:
                        assert max(image.size) <= 512
                        red, green, blue = image.convert("RGB").getpixel((0, 0))
                        assert blue > 200 and red < 30 and green < 30
        finally:
            client.close()
            assert stop(process) == 0
    print(json.dumps({"frozen_video_api": "passed", "cover_only": "rejected",
                      "selected_stream": 1, "blue_video_not_red_cover": True,
                      "sampled_frames": 3, "cloud_model": False, "profile_removed": True}))


if __name__ == "__main__":
    main()
