import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

from PIL import Image
import pytest

from server.services import video_input


def metadata(width=640, duration="2"):
    return {"metadata": {"streams": [{"codec_type": "video", "width": width, "height": 480}],
                         "format": {"duration": duration}}, "editing": "not_run"}


def test_optional_sampler_preserves_metadata_without_claiming_vision(monkeypatch):
    monkeypatch.setattr(video_input, "video_metadata", lambda *_: metadata())
    monkeypatch.setattr(shutil, "which", lambda _: None)
    result = video_input.extract_video("test.mp4", b"synthetic")
    assert result["images"] == [] and result["video_frame_status"] == "tool_missing"
    assert json.loads(result["text"])["visual_understanding"] == "not_run"
    assert result["video_transcription"] is False


@pytest.mark.parametrize("width,duration,status", [(100000, "2", "invalid_dimensions"), (640, "nan", "time_unavailable"), (640, "90000", "time_unavailable")])
def test_unsafe_dimensions_and_duration_never_start_decoder(monkeypatch, width, duration, status):
    monkeypatch.setattr(video_input, "video_metadata", lambda *_: metadata(width, duration))
    monkeypatch.setattr(shutil, "which", lambda _: "/trusted/ffmpeg")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("decoder must not run"))
    assert video_input.extract_video("test.mp4", b"x")["video_frame_status"] == status


def test_sampler_is_bounded_local_and_cleans_temporary_files(monkeypatch):
    monkeypatch.setattr(video_input, "video_metadata", lambda *_: metadata())
    monkeypatch.setattr(shutil, "which", lambda _: "/trusted/ffmpeg")
    folders = []
    def run(args, **kwargs):
        assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"
        assert args[args.index("-format_whitelist") + 1] == "mov,matroska,webm"
        assert args[args.index("-frames:v") + 1] == "1"
        assert kwargs["timeout"] == 8 and set(kwargs["env"]) == {"PATH", "HOME", "TMPDIR"}
        folders.append(Path(kwargs["cwd"]))
        Image.new("RGB", (8, 8), "red").save(args[-1])
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", run)
    result = video_input.extract_video("test.mp4", b"x")
    assert result["video_frame_status"] == "sampled"
    assert [x["source_locator"] for x in result["images"]] == ["test.mp4#t=0.000s", "test.mp4#t=1.000s", "test.mp4#t=1.800s"]
    assert all(not path.exists() for path in folders)
    assert result["images"][0]["data"] not in result["text"]
    from server.orchestrator.arslan import build_user_blocks
    blocks = build_user_blocks("inspect video", result["text"], result["images"])
    assert len([b for b in blocks if b["type"] == "image"]) == 3
    assert "test.mp4#t=1.000s" in blocks[3]["text"]
    from server.orchestrator.dispatcher import with_images
    assert "test.mp4#t=1.000s" in with_images("inspect video", result["images"])[3]["text"]


@pytest.mark.parametrize("successes,status", [(0, "decode_failed"), (1, "partial")])
def test_decoder_timeout_is_explicit_and_keeps_only_completed_frames(monkeypatch, successes, status):
    monkeypatch.setattr(video_input, "video_metadata", lambda *_: metadata())
    monkeypatch.setattr(shutil, "which", lambda _: "/trusted/ffmpeg")
    folders = []
    def run(args, **kwargs):
        folders.append(Path(kwargs["cwd"]))
        if len(folders) > successes:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        Image.new("RGB", (8, 8), "red").save(args[-1])
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(subprocess, "run", run)
    result = video_input.extract_video("test.mp4", b"x")
    assert result["video_frame_status"] == status
    assert len(result["images"]) == successes
    assert all(not path.exists() for path in folders)


def test_real_video_frames_are_bounded_and_source_addressed(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("optional local FFmpeg tools unavailable")
    source = tmp_path / "synthetic.mp4"
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x480:rate=10", "-t", "2", "-c:v", "libx264", str(source)],
                   check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = video_input.extract_video(source.name, source.read_bytes())
    assert result["video_frame_status"] == "sampled"
    assert len(result["images"]) == 3
    for payload in result["images"]:
        image = Image.open(io.BytesIO(base64.b64decode(payload["data"])))
        assert max(image.size) <= 512
    # Exercise the real provider payload builder; no network/model call occurs.
    from server.orchestrator.arslan import build_user_blocks
    from arslan.llm.providers.openai_provider import OpenAIProvider
    provider = OpenAIProvider(model="synthetic-vision", api_key="synthetic")
    blocks = build_user_blocks("inspect the sampled frames", result["text"], result["images"])
    payload = provider._payload(provider.build_messages("SYS", blocks, None), None, 0.7)
    user = [m for m in payload["messages"] if m["role"] == "user"][-1]
    assert len([part for part in user["content"] if part["type"] == "image_url"]) == 3
    assert any("synthetic.mp4#t=1.000s" in part.get("text", "") for part in user["content"])
    assert json.loads(result["text"])["transcript"] == "unavailable_no_transcription_adapter"
