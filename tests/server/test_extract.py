import pytest
from server.services import extract


async def test_extract_file_reuses_extractor(monkeypatch):
    monkeypatch.setattr(extract.ingest, "_extract_file", lambda fn, data: "hello extracted body")
    text, truncated = await extract.extract_text(filename="a.txt", data=b"x")
    assert "hello extracted body" in text
    assert truncated is False


async def test_extract_truncates_to_limit(monkeypatch):
    monkeypatch.setattr(extract.ingest, "_extract_file", lambda fn, data: "A" * 50)
    from unittest.mock import MagicMock
    fake_settings = MagicMock()
    fake_settings.attach_extract_char_limit = 10
    monkeypatch.setattr(extract, "settings", fake_settings)
    text, truncated = await extract.extract_text(filename="a.txt", data=b"x")
    assert len(text) == 10
    assert truncated is True


async def test_extract_url_uses_web_extract_executor(monkeypatch):
    from server.registry import executors
    class _Stub:
        async def execute(self, args):
            return {"ok": True, "url": args["url"], "text": "web body text"}
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Stub())
    text, _ = await extract.extract_text(url="https://example.com")
    assert "web body text" in text


async def test_extract_url_private_rejected(monkeypatch):
    from server.registry import executors
    class _Stub:
        async def execute(self, args):
            return {"ok": False, "error": "private address"}
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Stub())
    with pytest.raises(ValueError):
        await extract.extract_text(url="http://169.254.169.254/")


def _tiny_png() -> bytes:
    """A real PNG with rendered text (OCR itself is monkeypatched in tests)."""
    import io
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (120, 40), "white")
    ImageDraw.Draw(img).text((4, 12), "HELLO", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def test_extract_image_ocr(monkeypatch):
    # The `ocr` extra is opt-in and is NOT in the packaged desktop build
    # (S4.3-a). Skip rather than error so a plain `pip install .` checkout
    # is green; CI installs --extra ocr so these DO run there.
    pytesseract = pytest.importorskip("pytesseract")
    monkeypatch.setattr(pytesseract, "image_to_string", lambda img, **kw: "OCR text 已识别")
    text, truncated = await extract.extract_text(filename="shot.png", data=_tiny_png())
    assert "OCR text 已识别" in text
    assert truncated is False


async def test_extract_image_ocr_failure_returns_empty(monkeypatch):
    # The `ocr` extra is opt-in and is NOT in the packaged desktop build
    # (S4.3-a). Skip rather than error so a plain `pip install .` checkout
    # is green; CI installs --extra ocr so these DO run there.
    pytesseract = pytest.importorskip("pytesseract")
    def _boom(img, **kw):
        raise RuntimeError("tesseract not installed")
    monkeypatch.setattr(pytesseract, "image_to_string", _boom)
    text, truncated = await extract.extract_text(filename="shot.png", data=_tiny_png())
    assert text == ""
    assert truncated is False


async def test_extract_image_ocr_whitespace_is_empty(monkeypatch):
    # The `ocr` extra is opt-in and is NOT in the packaged desktop build
    # (S4.3-a). Skip rather than error so a plain `pip install .` checkout
    # is green; CI installs --extra ocr so these DO run there.
    pytesseract = pytest.importorskip("pytesseract")
    monkeypatch.setattr(pytesseract, "image_to_string", lambda img, **kw: " \n\f ")
    text, _ = await extract.extract_text(filename="shot.png", data=_tiny_png())
    assert text == ""


async def test_extract_image_bad_bytes_returns_empty():
    # Undecodable image bytes → best-effort '' (never raises to the API layer).
    text, _ = await extract.extract_text(filename="shot.jpg", data=b"not an image")
    assert text == ""
