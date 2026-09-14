import io

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from server.services import extract, ingest


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
        page[NameObject("/Contents")] = content
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
