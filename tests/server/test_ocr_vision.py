"""Tier-2 OCR: the system's own text recogniser.

These tests run the REAL macOS Vision framework wherever the host provides it.
That is deliberate. The capability this module replaces (pytesseract) passed its
tests for months while being completely absent from every packaged build,
because the tests never asked the recogniser to recognise anything — they
asserted on a wrapper that returns "" when the engine is missing, which is
exactly what a working engine returns for a blank page.

So: an image is generated here, in the repo, with text on it, and the assertion
is that the text comes back. Nothing external, nothing mocked on the happy path.
"""
from __future__ import annotations

import io
import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

from server.services import ocr_vision

macos_only = pytest.mark.skipif(
    sys.platform != "darwin", reason="Vision is a macOS framework"
)


def _font(size: int):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _png(lines: list[str], *, size=(900, 240)) -> bytes:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((30, 30 + i * 80), line, fill="black", font=_font(48))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------
# The capability itself. If these fail, the feature does not exist — which is
# the whole point of writing them against the real framework.
# --------------------------------------------------------------------------

@macos_only
def test_it_actually_reads_text_off_an_image():
    text, status = ocr_vision.recognize(_png(["Arslan reads this line"]),
                                        languages=("en-US",))
    assert status == ocr_vision.OK
    assert "Arslan reads this line" in text


@macos_only
def test_it_reads_chinese_too():
    text, status = ocr_vision.recognize(_png(["第二大脑读到这一行"]),
                                        languages=("zh-Hans", "en-US"))
    assert status == ocr_vision.OK
    assert "第二大脑" in text


@macos_only
def test_a_blank_page_is_no_text_not_an_error():
    """The distinction the old path could not make: nothing found vs broken.

    _ocr_image collapsed both into "", which is how a missing engine passed for
    'this image has no writing on it'."""
    blank = Image.new("RGB", (400, 200), "white")
    buf = io.BytesIO()
    blank.save(buf, "PNG")
    text, status = ocr_vision.recognize(buf.getvalue(), languages=("en-US",))
    assert (text, status) == ("", ocr_vision.NO_TEXT)


@macos_only
def test_undecodable_bytes_are_an_error_not_no_text():
    text, status = ocr_vision.recognize(b"this is not an image",
                                        languages=("en-US",))
    assert text == ""
    assert status == ocr_vision.ERROR


# --------------------------------------------------------------------------
# The hard gate (decision (3)): a language the host cannot recognise means we
# do not run at all. Not "run and hope", not "run and filter by confidence" —
# the confidence measurement showed a correct English line and a scrambled
# Uyghur one both score 0.500, so a threshold cannot tell them apart.
# --------------------------------------------------------------------------

def test_an_unsupported_language_is_refused_before_vision_is_touched(monkeypatch):
    """Asserts the ORDER, not just the outcome.

    A gate placed after the call would produce the same (text, status) while
    still having asked a recogniser to guess at a script it does not know —
    which is precisely how the scrambled-Uyghur result was produced in the
    experiment. So the assertion is that the framework is never reached."""
    calls = []

    class Tripwire:
        def __getattr__(self, name):
            calls.append(name)
            raise AssertionError("Vision was called for an unsupported language")

    monkeypatch.setattr(ocr_vision, "_vision", lambda: Tripwire())
    monkeypatch.setattr(ocr_vision, "supported_languages", lambda: ("en-US", "fr-FR"))

    text, status = ocr_vision.recognize(_png(["anything"]), languages=("ug",))

    assert (text, status) == ("", ocr_vision.UNSUPPORTED_LANGUAGE)
    assert calls == []


def test_one_supported_language_among_several_is_enough(monkeypatch):
    monkeypatch.setattr(ocr_vision, "supported_languages", lambda: ("en-US",))
    seen = {}

    def fake_run(data, langs):
        seen["langs"] = langs
        return "ran", ocr_vision.OK

    monkeypatch.setattr(ocr_vision, "_recognize_now", fake_run)
    text, status = ocr_vision.recognize(b"x", languages=("ug", "en-US"))
    assert (text, status) == ("ran", ocr_vision.OK)
    # The unsupported one is dropped rather than passed through to Vision:
    # handing it a language it does not know is how the fake result appeared.
    assert seen["langs"] == ("en-US",)


# --------------------------------------------------------------------------
# The language list is asked for at runtime. Vision's set grows with the OS
# version, so a literal here would claim on macOS 11 whatever this machine
# happens to support today.
# --------------------------------------------------------------------------

def test_the_supported_list_comes_from_the_framework_not_from_us(monkeypatch):
    """Discriminating: a hardcoded tuple would ignore this substitution."""
    class FakeRequest:
        @staticmethod
        def alloc():
            return FakeRequest()

        def init(self):
            return self

        def supportedRecognitionLanguagesAndReturnError_(self, _):
            return (["xx-XX", "yy-YY"], None)

    class FakeVision:
        VNRecognizeTextRequest = FakeRequest

    monkeypatch.setattr(ocr_vision, "_vision", lambda: FakeVision())
    ocr_vision.supported_languages.cache_clear()
    try:
        assert ocr_vision.supported_languages() == ("xx-XX", "yy-YY")
    finally:
        ocr_vision.supported_languages.cache_clear()


@macos_only
def test_the_real_host_reports_a_plausible_language_set():
    langs = ocr_vision.supported_languages()
    assert "en-US" in langs
    # Not an arbitrary sanity check: decision (3) exists BECAUSE Uyghur is
    # absent. If a future macOS adds it, this test fails and the gate's
    # rationale — and the README's language note — need revisiting.
    assert not any(t.startswith("ug") for t in langs), (
        "macOS now recognises Uyghur; revisit the README language note "
        "and the rationale recorded in the spec's section 0.4"
    )


def test_a_host_without_vision_says_so_rather_than_raising(monkeypatch):
    monkeypatch.setattr(ocr_vision, "_vision", lambda: None)
    ocr_vision.supported_languages.cache_clear()
    try:
        assert ocr_vision.is_available() is False
        assert ocr_vision.recognize(b"x", languages=("en-US",)) == (
            "", ocr_vision.UNSUPPORTED_PLATFORM)
    finally:
        ocr_vision.supported_languages.cache_clear()
