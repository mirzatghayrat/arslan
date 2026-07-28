"""_ocr_pdf's RASTERIZER, exercised for real (S4.3-a).

Why this file exists: the pre-existing OCR tests (test_ingest_ocr.py) all
monkeypatch ``ingest._ocr_pdf`` itself, so they pass identically whether the
rasterizer is pymupdf, pypdfium2, or a stub that returns "". They have ZERO
discriminating power over the thing S4.3-a actually changed. Swapping the
AGPL pymupdf for pypdfium2 would have been "all green" with no test proving
a single page was ever rendered.

So here we stub only ``pytesseract.image_to_string`` — the *recognize* step —
and let the real *rasterize* step run, then assert on what the rasterizer
actually produced: page count, page ORDER, and the dpi-scaled pixel size of
each page. A rasterizer that renders nothing, renders one page, renders them
backwards, or ignores the dpi all fail here.
"""
from __future__ import annotations

import io
import math

import pytest

from server.services import ingest

pypdfium2 = pytest.importorskip(
    "pypdfium2",
    reason="the 'ocr' extra is not installed — CI must run with --extra ocr, "
    "otherwise this whole file silently skips and the swap is unverified",
)

# _ocr_pdf renders at this dpi; PDF user-space is 72 units per inch.
_DPI = 200
_SCALE = _DPI / 72.0

# Two DIFFERENT page sizes, in a deliberate order: a test that only counted
# pages, or that rendered page 2 twice, would pass. Distinct sizes make the
# per-page assertion identify WHICH page it got, and in what order.
_PAGE_A = (612, 792)  # US Letter
_PAGE_B = (200, 100)  # a wide, tiny page — nothing like A


def _blank_pdf(sizes: list[tuple[int, int]]) -> bytes:
    """A PDF of blank pages, built with pypdf (BSD, already a core dep).

    Blank on purpose: _extract_file only reaches the OCR path when the text
    layer yields < _OCR_MIN_CHARS characters.
    """
    from pypdf import PdfWriter

    writer = PdfWriter()
    for w, h in sizes:
        writer.add_blank_page(width=w, height=h)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _expected_px(size: tuple[int, int]) -> tuple[int, int]:
    """Exact expected pixel size — deliberately not a tolerance.

    CEIL, not truncation: 200pt at 200dpi is 555.55px and pypdfium2 renders
    556. (Letter's 612x792 lands on whole pixels, which is why _PAGE_B — a
    size that does NOT divide evenly — is in the fixture at all: a truncating
    or rounding rasterizer is indistinguishable on _PAGE_A alone.)

    Pinning the exact value is the point: these numbers ARE the rasterizer's
    fingerprint. If a future dependency bump changes them, the rasterizer's
    output geometry changed and that should surface as a red test, not be
    absorbed by a fuzzy assertion.
    """
    w, h = size
    return (math.ceil(w * _SCALE), math.ceil(h * _SCALE))


def test_the_fixture_pdf_really_has_no_text_layer():
    """Pre-assertion (class 0): without this, every test below could be vacuous.

    If the fixture accidentally carried a text layer, _extract_file would
    return that text and never call the rasterizer at all — and the OCR
    assertions would be asserting about a code path that never ran.
    """
    data = _blank_pdf([_PAGE_A])
    assert ingest._pdf_text_layer(data).strip() == ""
    assert len(ingest._pdf_text_layer(data).strip()) < ingest._OCR_MIN_CHARS


def test_ocr_pdf_rasterizes_every_page_in_order_at_the_configured_dpi(monkeypatch):
    """The core discriminating test: real rasterization, stubbed recognition."""
    seen: list[tuple[int, int]] = []

    def _record(img, **kw):
        seen.append((img.width, img.height))
        return f"page-{len(seen)}"

    monkeypatch.setattr("pytesseract.image_to_string", _record)

    text = ingest._ocr_pdf(_blank_pdf([_PAGE_A, _PAGE_B]))

    # Page COUNT — a rasterizer that bailed after page 1 fails here.
    assert len(seen) == 2, f"expected 2 rendered pages, got {len(seen)}: {seen}"
    # Page ORDER and IDENTITY — distinct sizes make this unambiguous.
    assert seen[0] == _expected_px(_PAGE_A)
    assert seen[1] == _expected_px(_PAGE_B)
    # And the two are genuinely different, so the assertion above cannot be
    # satisfied by rendering the same page twice.
    assert seen[0] != seen[1]
    # The recognized text of every page is joined into the result.
    assert "page-1" in text and "page-2" in text


def test_whatever_the_rasterizer_returns_is_normalized_to_rgb(monkeypatch):
    """Pins the .convert("RGB") normalization — by forcing a non-RGB input.

    Measured on pypdfium2 5.12.1: PdfBitmap.to_pil() already returns mode
    "RGB" for our render call, so asserting the mode of a REAL render passes
    with or without the convert — a green mutation, i.e. an assertion with no
    discriminating power. (First draft of this file made exactly that mistake,
    and its docstring asserted a BGRA behaviour that measurement disproved.)

    So stub to_pil() to hand back RGBA — the mode a transparency-carrying
    render would produce — and assert pytesseract still receives RGB. Now the
    convert is the only thing standing between the two, and deleting it turns
    this red.
    """
    from PIL import Image

    monkeypatch.setattr(
        pypdfium2.PdfBitmap, "to_pil", lambda self: Image.new("RGBA", (7, 11))
    )
    got: list[tuple[str, tuple[int, int]]] = []
    monkeypatch.setattr(
        "pytesseract.image_to_string",
        lambda img, **kw: got.append((img.mode, img.size)) or "x",
    )

    ingest._ocr_pdf(_blank_pdf([_PAGE_A]))

    assert got == [("RGB", (7, 11))], (
        "pytesseract must receive an RGB image; the stub supplied RGBA, so a "
        "missing .convert('RGB') shows up here"
    )


def test_ocr_pdf_is_best_effort_when_recognition_blows_up(monkeypatch):
    """The existing contract: OCR failure degrades to '' rather than raising.

    Pinned here because S4.3-a ships WITHOUT the ocr extra, so this is the
    path every packaged install takes.
    """
    def _boom(img, **kw):
        raise RuntimeError("tesseract binary is not installed")

    monkeypatch.setattr("pytesseract.image_to_string", _boom)
    assert ingest._ocr_pdf(_blank_pdf([_PAGE_A])) == ""


def _extract_with_text_layer(monkeypatch, layer_text: str) -> tuple[str, bool]:
    """Run _extract_file on a PDF whose text layer is `layer_text`.

    Returns (result, did_ocr_run). The text layer is stubbed rather than
    embedded in a real PDF because the behaviour under test is _extract_file's
    THRESHOLD decision, and a hand-rolled content stream would test pypdf's
    text extractor instead.
    """
    ran = False

    def _tripwire(data):
        nonlocal ran
        ran = True
        return "OCR-RAN"

    # The behaviour under test is the THRESHOLD, which is engine-agnostic. On a
    # host with the system recogniser _extract_file takes the Vision branch and
    # never reaches _ocr_pdf, so the tesseract engine is selected explicitly
    # here — that is a real configuration (Linux/source, decision ④A), not a
    # convenience. The same threshold on the Vision branch is pinned by
    # test_the_threshold_holds_on_the_system_recogniser_path below.
    from server.services import ocr_vision

    monkeypatch.setattr(ocr_vision, "is_available", lambda: False)
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: layer_text)
    monkeypatch.setattr(ingest, "_ocr_pdf", _tripwire)
    return ingest._extract_file("doc.pdf", _blank_pdf([_PAGE_A])), ran


def test_ocr_runs_only_when_the_text_layer_is_too_short(monkeypatch):
    """BOTH halves — this is what makes the assertion discriminating.

    Asserting only the empty-layer case would be satisfied by an
    unconditional "always OCR" implementation, which would burn time and
    tokens on every text PDF. Asserting only the rich case would be satisfied
    by "never OCR". The pair pins the threshold itself.
    """
    rich = "x" * (ingest._OCR_MIN_CHARS + 1)
    result_rich, ran_rich = _extract_with_text_layer(monkeypatch, rich)
    assert ran_rich is False, "a PDF that already has text must not be rasterized"
    assert result_rich == rich

    result_empty, ran_empty = _extract_with_text_layer(monkeypatch, "")
    assert ran_empty is True, "a PDF with no text layer must fall back to OCR"
    assert result_empty == "OCR-RAN"

    # The two branches genuinely differ — guards against a stub/threshold that
    # collapses both cases onto one answer.
    assert ran_rich != ran_empty and result_rich != result_empty


def test_ocr_output_is_discarded_when_it_finds_nothing(monkeypatch):
    """Empty OCR must not shadow the (short) text layer that did exist.

    ingest.py only returns the OCR result `if ocr.strip()`. Without this test,
    dropping that guard would silently replace a 5-character text layer with
    "" — a regression invisible to every other test here.
    """
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: "short")
    monkeypatch.setattr(ingest, "_ocr_pdf", lambda data: "   \n  ")
    assert ingest._extract_file("doc.pdf", _blank_pdf([_PAGE_A])) == "short"


def test_the_threshold_holds_on_the_system_recogniser_path(monkeypatch):
    """The same both-halves assertion, on the branch that actually ships.

    The pair above selects the tesseract engine to pin the threshold; without
    this twin, the shipping (Vision) branch could rasterise every text PDF and
    nothing would notice."""
    from server.services import ocr_vision

    calls = []

    def _spy(data, ui_language):
        calls.append(1)
        return ["[page 1]\nread by the system recogniser"]

    monkeypatch.setattr(ocr_vision, "is_available", lambda: True)
    monkeypatch.setattr(ingest, "_ocr_pdf_pages_locally", _spy)

    rich = "x" * (ingest._OCR_MIN_CHARS + 1)
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: rich)
    assert ingest._extract_file("doc.pdf", _blank_pdf([_PAGE_A])) == rich
    assert calls == [], "a PDF that already has text was rasterized anyway"

    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: "")
    out = ingest._extract_file("doc.pdf", _blank_pdf([_PAGE_A]))
    assert "read by the system recogniser" in out
    assert calls == [1]


def test_a_scan_the_recogniser_cannot_read_falls_through_instead_of_shadowing(
        monkeypatch):
    """The regression the existing suite caught during this round.

    Returning page-shaped placeholders when NO page yielded text is non-empty,
    so it would (a) shadow a short but real text layer and (b) skip the
    tesseract path a Linux install still depends on."""
    from server.services import ocr_fallback, ocr_vision

    monkeypatch.setattr(ocr_vision, "is_available", lambda: True)
    monkeypatch.setattr(ocr_fallback, "read_locally",
                        lambda data, ui_language=None: ("", ocr_vision.NO_TEXT))
    monkeypatch.setattr(ingest, "_pdf_text_layer", lambda data: "short")
    monkeypatch.setattr(ingest, "_ocr_pdf", lambda data: "")

    assert ingest._extract_file("doc.pdf", _blank_pdf([_PAGE_A])) == "short"
