"""Real image bytes reach the adapter as decoded, bounded PNG, never MIME lies."""
import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from server.services import ingest, llm_factory, ocr_fallback


def picture(fmt="PNG", size=(32, 16), **kwargs):
    buf = io.BytesIO()
    with Image.new("RGB", size, "red") as img:
        img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


@pytest.fixture
def adapter(monkeypatch):
    calls = []

    async def chat(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content="A red rectangle.")

    async def build(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(chat=chat)

    monkeypatch.setattr(llm_factory, "build_adapter", build)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "TIFF", "WEBP", "GIF", "BMP"])
async def test_actual_format_is_decoded_not_mislabeled(fmt, adapter):
    result = await ingest.describe_image(picture(fmt), "image/png")
    assert result == "A red rectangle."
    assert adapter[0] == {"role": "converse"}
    block = adapter[1]["user"][1]
    assert block["mime_type"] == "image/png"
    payload = base64.b64decode(block["data"])
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(payload)) as img:
        img.load()
        assert img.size == (32, 16)
        assert img.getpixel((0, 0))[0] >= 250


def test_downscale_orientation_and_source_metadata():
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private metadata, not image content"
    payload, multiple = ingest._vision_png(picture("JPEG", (3200, 1600), exif=exif))
    assert not multiple
    with Image.open(io.BytesIO(payload)) as img:
        assert img.size == (784, 1568)
        assert not img.getexif()
        assert "exif" not in img.info
    assert b"private metadata" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["GIF", "TIFF"])
async def test_multiple_frames_read_first_and_disclose_limit(fmt, adapter):
    with Image.new("RGB", (32, 16), "blue") as second:
        data = picture(fmt, save_all=True, append_images=[second])
    result = await ingest.describe_image(data, "wrong/type")
    assert result.startswith(ingest._FIRST_FRAME_NOTE)
    assert "Only the first frame/page" in adapter[1]["user"][0]["text"]
    with Image.open(io.BytesIO(base64.b64decode(adapter[1]["user"][1]["data"]))) as img:
        assert img.getpixel((0, 0)) == (255, 0, 0, 255)


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [b"", b"not a picture", b"\x89PNG\r\n\x1a\n", b"\0\0\0\x18ftypheic"])
async def test_unreadable_input_never_constructs_adapter(data, adapter):
    with pytest.raises((ValueError, OSError)) as exc:
        await ingest.describe_image(data, "image/png")
    assert adapter == []
    assert not ocr_fallback.model_refused_the_image(str(exc.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,value,match", [
    ("IMAGE_MAX_INPUT_BYTES", 1, "input byte"),
    ("IMAGE_MAX_PIXELS", 1, "input pixel"),
    ("IMAGE_MAX_PAYLOAD_BYTES", 1, "output byte"),
])
async def test_limits_fail_before_adapter(monkeypatch, adapter, limit, value, match):
    monkeypatch.setattr(ingest, limit, value)
    with pytest.raises(ValueError, match=match):
        await ingest.describe_image(picture(), "image/png")
    assert adapter == []


@pytest.mark.asyncio
async def test_provider_failure_is_not_changed_by_normalization(monkeypatch):
    async def build(**kwargs):
        raise RuntimeError("401 invalid API key")

    monkeypatch.setattr(llm_factory, "build_adapter", build)
    with pytest.raises(RuntimeError, match="401 invalid API key"):
        await ingest.describe_image(picture(), "image/png")
