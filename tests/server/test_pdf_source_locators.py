import io
import pytest

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from server.services import extract, ingest


async def test_same_page_scan_is_not_hidden_by_native_caption(monkeypatch):
    from scripts.mixed_pdf_ocr_smoke import fixture
    data = fixture(same_page=True)
    layer = ingest._pdf_text_layer(data)
    assert layer.unread_pages == ()
    assert layer.image_text_pages == (1,)
    assert layer.ocr_pages == (1,)
    assert layer.pages[1].strip() == "Native caption stays exact."
    calls = []
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: True)
    def recognize(png, **kwargs):
        calls.append(png)
        return "Scanned source recovered 2468.\nNative caption stays exact.", ingest.ocr_vision.OK
    monkeypatch.setattr(ingest.ocr_fallback, "read_locally", recognize)
    text, partial = await extract.extract_text(filename="same-page.pdf", data=data)
    assert len(calls) == 1 and not partial
    assert "[page 2]\nNative caption stays exact." in text
    assert "[local OCR of whole page; may repeat native text]" in text
    assert "Scanned source recovered 2468." in text


async def test_same_page_unavailable_keeps_caption_and_reports_partial(monkeypatch):
    from scripts.mixed_pdf_ocr_smoke import fixture
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    text, partial = await extract.extract_text(filename="same-page.pdf", data=fixture(same_page=True))
    assert partial
    assert "[page 2]\nNative caption stays exact." in text
    assert "[additional image text not read: unavailable]" in text
    assert '"unread_pages": [2]' in text


async def test_broken_image_inventory_does_not_discard_readable_native_text(monkeypatch):
    from pypdf._page import VirtualListImages
    def broken(*args):
        raise ValueError("synthetic damaged image resource")
    monkeypatch.setattr(VirtualListImages, "keys", broken)
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    data = pdf_with_pages(["Readable native source must survive."])
    text, partial = await extract.extract_text(filename="damaged-image.pdf", data=data)
    assert partial
    assert "[page 1]\nReadable native source must survive." in text
    assert "[additional image text not read: unavailable]" in text
    assert '"unread_pages": [1]' in text
    assert "synthetic damaged" not in text


async def test_real_broken_form_resource_retains_native_text(monkeypatch):
    from pypdf import PdfReader
    from pypdf.generic import NumberObject
    writer = PdfWriter()
    page = writer.add_page(PdfReader(io.BytesIO(pdf_with_pages([
        "Native source survives malformed optional resources."]))).pages[0])
    broken = DecodedStreamObject()
    broken.set_data(b"")
    broken.update({NameObject("/Subtype"): NameObject("/Form"),
                   NameObject("/Resources"): NumberObject(7)})
    page["/Resources"][NameObject("/XObject")] = DictionaryObject({
        NameObject("/Broken"): writer._add_object(broken)})
    output = io.BytesIO()
    writer.write(output)
    data = output.getvalue()
    parsed = PdfReader(io.BytesIO(data)).pages[0]
    assert "Native source survives" in parsed.extract_text()
    with pytest.raises(TypeError):
        parsed.images.keys()
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    text, partial = await extract.extract_text(filename="broken-form.pdf", data=data)
    assert partial
    assert "Native source survives malformed optional resources." in text
    assert "[additional image text not read: unavailable]" in text


def mixed_pdf():
    from pypdf import PdfReader
    writer = PdfWriter()
    reader = PdfReader(io.BytesIO(pdf_with_pages([
        "Native source must stay exactly as written.", "", "", "Last native source."])))
    for page in reader.pages:
        writer.add_page(page)
    # Real drawing-only page, no text operators. Rasterization is real; OCR is
    # stubbed in contract tests so they do not depend on the host recognizer.
    content = DecodedStreamObject()
    content.set_data(b"0 0 0 rg 20 20 100 100 re f")
    writer.pages[1][NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_mixed_pdf_detects_content_without_treating_blank_pages_as_scans():
    layer = ingest._pdf_text_layer(mixed_pdf())
    assert layer.has_text
    assert layer.unread_pages == (1,)


def test_mixed_fixture_really_renders_ink_not_just_parseable_operators():
    import pypdfium2
    pdf = pypdfium2.PdfDocument(mixed_pdf())
    page = pdf[1]
    bitmap = page.render(scale=1)
    image = bitmap.to_pil().convert("RGB")
    try:
        assert image.getextrema() == ((0, 255), (0, 255), (0, 255))
    finally:
        image.close()
        bitmap.close()
        page.close()
        pdf.close()


def test_empty_content_stream_is_not_an_unread_scan():
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    content = DecodedStreamObject()
    content.set_data(b" \n ")
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    assert ingest._pdf_text_layer(output.getvalue()).unread_pages == ()


def test_mixed_pdf_recognizer_exception_retains_native_pages(monkeypatch):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: True)
    def failed(*args, **kwargs):
        raise RuntimeError("synthetic recognizer failure")
    monkeypatch.setattr(ingest.ocr_fallback, "read_locally", failed)
    data = mixed_pdf()
    text, partial = ingest._mixed_pdf_text(data, ingest._pdf_text_layer(data), "en")
    assert partial and "[page text not read: error]" in text
    assert "[page 4]\nLast native source." in text
    assert "synthetic recognizer failure" not in text


async def test_mixed_pdf_ocr_only_missing_page_and_preserves_sources(monkeypatch):
    calls = []
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: True)
    def recognize(png, **kwargs):
        assert png.startswith(b"\x89PNG")
        calls.append(kwargs)
        return "Scanned source recovered.", ingest.ocr_vision.OK
    monkeypatch.setattr(ingest.ocr_fallback, "read_locally", recognize)
    text, truncated = await extract.extract_text(filename="mixed.pdf", data=mixed_pdf())
    assert not truncated
    assert len(calls) == 1
    assert "[page 1]\nNative source must stay exactly as written." in text
    assert "[page 2]\n[local OCR]\nScanned source recovered." in text
    assert "[page 3]" not in text
    assert "[page 4]\nLast native source." in text


async def test_mixed_pdf_unavailable_is_explicit_partial_not_silent_success(monkeypatch):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    text, truncated = await extract.extract_text(filename="mixed.pdf", data=mixed_pdf())
    assert truncated
    assert "[page 2]\n[page text not read: unavailable]" in text
    assert '"unread_pages": [2]' in text
    assert "Last native source." in text


def test_mixed_pdf_no_text_status_does_not_promote_diagnostic_to_source(monkeypatch):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: True)
    monkeypatch.setattr(ingest.ocr_fallback, "read_locally",
                        lambda *a, **k: ("not source", ingest.ocr_vision.NO_TEXT))
    data = mixed_pdf()
    text, partial = ingest._mixed_pdf_text(data, ingest._pdf_text_layer(data), "en")
    assert partial and "not source" not in text
    assert "[page text not read: no_text]" in text


def test_mixed_pdf_page_budget_retains_native_text_beyond_budget(monkeypatch):
    monkeypatch.setattr(ingest, "VISION_PDF_MAX_PAGES", 0)
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    data = mixed_pdf()
    text, partial = ingest._mixed_pdf_text(data, ingest._pdf_text_layer(data), "en")
    assert partial and "page_limit" in text
    assert "[page 4]\nLast native source." in text


async def test_mixed_knowledge_pdf_preserves_unread_page_notice_without_model(monkeypatch):
    captured = []
    async def store(spawn_id, filename, text, **kwargs):
        captured.append(text)
        return 1
    async def forbidden(*args):
        raise AssertionError("Mixed text PDF must not start a model request")
    monkeypatch.setattr(ingest, "ingest_text", store)
    monkeypatch.setattr(ingest, "describe_image", forbidden)
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    assert await ingest.ingest_file(1, "mixed.pdf", mixed_pdf()) == 1
    assert '"unread_pages": [2]' in captured[0]
    assert "Native source must stay exactly as written." in captured[0]


def pdf_with_pages(texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=300, height=300)
        if not text:
            continue
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})})})
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 20 250 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_real_pdf_preserves_page_numbers_across_blank_pages():
    data = pdf_with_pages(["First page has enough readable content.", "", "Third page source."])
    layer = ingest._pdf_text_layer(data)
    assert layer.has_text
    assert layer.located_text == "[page 1]\nFirst page has enough readable content.\n\n[page 3]\nThird page source."
    assert ingest._extract_file("source.pdf", data) == layer.located_text


def test_empty_pages_and_locators_never_count_as_read_content(monkeypatch):
    data = pdf_with_pages(["a"] + [""] * 30 + ["b"])
    layer = ingest._pdf_text_layer(data)
    assert len(layer.located_text) >= ingest._OCR_MIN_CHARS
    assert not layer.has_text
    calls = []
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    monkeypatch.setattr(ingest, "_ocr_pdf", lambda data: calls.append("ocr") or "")
    assert ingest._extract_file("short.pdf", data) == "[page 1]\na\n\n[page 32]\nb"
    assert calls == ["ocr"]


def test_all_blank_pdf_has_no_fabricated_text():
    layer = ingest._pdf_text_layer(pdf_with_pages(["", "", ""]))
    assert not layer.has_text
    assert layer.located_text == ""


async def test_ephemeral_pdf_does_not_compress_source_locators(monkeypatch):
    async def forbidden(*args):
        raise AssertionError("PDF source locators must not be summarized away")
    monkeypatch.setattr(ingest, "_compress", forbidden)
    data = pdf_with_pages(["This is sufficient source text.", "", "A later page."])
    text, truncated = await extract.extract_text(filename="source.PDF", data=data, compress=True)
    assert "[page 3]\nA later page." in text
    assert not truncated


async def test_knowledge_pdf_receives_source_locators_without_vision(monkeypatch):
    captured = []
    async def store(spawn_id, filename, text, **kwargs):
        captured.append(text)
        return 1
    async def forbidden(*args):
        raise AssertionError("Text PDF must not invoke image description")
    monkeypatch.setattr(ingest, "ingest_text", store)
    monkeypatch.setattr(ingest, "describe_image", forbidden)
    assert await ingest.ingest_file(1, "source.pdf", pdf_with_pages(["Enough source text to use the text layer.", "", "Third page."])) == 1
    assert "[page 3]\nThird page." in captured[0]
