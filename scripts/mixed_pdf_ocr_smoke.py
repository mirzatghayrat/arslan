"""Offline, in-memory mixed-PDF check with the real host OCR (not a mock).

Run with the repository Python. No document is saved, no model is contacted,
and no user profile is opened. Synthetic inputs only.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile

import pypdfium2 as pdfium
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from server.services import ingest, ocr_vision


def text_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=240)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): DictionaryObject({NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica")})})})
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 24 Tf 30 140 Td ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def fixture(*, same_page: bool = False) -> bytes:
    from pypdf import PdfReader, Transformation

    writer = PdfWriter()
    native = "Native source remains unchanged."
    writer.add_page(PdfReader(io.BytesIO(text_pdf(native))).pages[0])
    # Render text to pixels, then embed ONLY the RGB pixels in page 2.
    # A text-layer-only extractor cannot find this sentence.
    pdf = pdfium.PdfDocument(text_pdf("Scanned source recovered 2468."))
    page = pdf[0]
    bitmap = page.render(scale=2)
    image = bitmap.to_pil().convert("RGB")
    try:
        scan = DecodedStreamObject()
        scan.set_data(image.tobytes())
        scan.update({NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(image.width),
            NameObject("/Height"): NumberObject(image.height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8)})
        target = writer.add_blank_page(width=600, height=240)
        target[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"):
            DictionaryObject({NameObject("/Scan"): writer._add_object(scan)})})
        content = DecodedStreamObject()
        content.set_data(b"q 600 0 0 240 0 0 cm /Scan Do Q")
        target[NameObject("/Contents")] = writer._add_object(content)
        if same_page:
            overlay = PdfReader(io.BytesIO(text_pdf("Native caption stays exact."))).pages[0]
            target.merge_transformed_page(overlay, Transformation().translate(0, -90))
    finally:
        image.close()
        bitmap.close()
        page.close()
        pdf.close()
    writer.add_blank_page(width=600, height=240)
    writer.add_page(PdfReader(io.BytesIO(text_pdf("Final native source retained."))).pages[0])
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def main() -> None:
    data = fixture()
    layer = ingest._pdf_text_layer(data)
    assert layer.unread_pages == (1,) and not layer.pages[1].strip()
    if len(sys.argv) > 1:
        from scripts.frozen_sidecar_smoke import start, stop
        binary = Path(sys.argv[1]).resolve()
        assert binary.is_relative_to(Path(tempfile.gettempdir()).resolve())
        assert any(part.startswith(("arslan-candidate-build.", "arslan-native-candidate."))
                   for part in binary.parts)
        assert binary.name == "arslan-server" and binary.is_file()
        with tempfile.TemporaryDirectory(prefix="arslan-mixed-pdf-smoke-") as folder:
            process, client, _ = start(binary, Path(folder))
            try:
                response = client.put("/api/v1/settings", json={"language": "en", "ocr_languages": "en-US"})
                assert response.status_code == 200
                response = client.post("/api/v1/extract",
                    files={"file": ("mixed-fixture.pdf", data, "application/pdf")},
                    data={"compress": "true"}, timeout=30)
                assert response.status_code == 200, response.status_code
                result = response.json()
                text, partial = result["text"], result["truncated"]
                response = client.post("/api/v1/extract",
                    files={"file": ("same-page.pdf", fixture(same_page=True), "application/pdf")}, timeout=30)
                assert response.status_code == 200
                same = response.json()
                check_same_page(same["text"], same["truncated"])
                # An explicitly unsupported OCR language must preserve native
                # text while exposing partial extraction, not fake success.
                response = client.put("/api/v1/settings", json={"ocr_languages": "zz-ZZ"})
                assert response.status_code == 200
                response = client.post("/api/v1/extract",
                    files={"file": ("mixed-fixture.pdf", data, "application/pdf")}, timeout=30)
                assert response.status_code == 200
                incomplete = response.json()
                assert incomplete["truncated"] is True
                assert "[page text not read: unsupported_language]" in incomplete["text"]
                assert '"unread_pages": [2]' in incomplete["text"]
                assert "[page 4]\nFinal native source retained." in incomplete["text"]
                assert "Scanned source recovered" not in incomplete["text"]
            finally:
                client.close()
                assert stop(process) == 0
    else:
        assert ocr_vision.is_available(), "Real host OCR is unavailable; acceptance not performed"
        text, partial = ingest._mixed_pdf_text(data, layer, "en", "en-US")
        same_data = fixture(same_page=True)
        same_layer = ingest._pdf_text_layer(same_data)
        assert same_layer.image_text_pages == (1,)
        check_same_page(*ingest._mixed_pdf_text(same_data, same_layer, "en", "en-US"))
    assert not partial, text
    assert "[page 1]\nNative source remains unchanged." in text
    assert "[page 2]\n[local OCR]\nScanned source recovered 2468." in text
    assert "[page 3]" not in text
    assert "[page 4]\nFinal native source retained." in text
    print(json.dumps({"real_host_ocr": True, "mixed_pdf": "passed",
        "native_text_preserved": True, "scan_has_no_text_layer": True,
        "page_locators": [1, 2, 4], "partial": partial, "cloud_model": False,
        "same_page_text_and_scan": True, "frozen_api": len(sys.argv) > 1,
        "unsupported_language_partial": len(sys.argv) > 1}))


def check_same_page(text: str, partial: bool) -> None:
    assert not partial, text
    assert "[page 2]\nNative caption stays exact." in text
    assert "[local OCR of whole page; may repeat native text]" in text
    assert "Scanned source recovered 2468." in text
    assert "[page 4]\nFinal native source retained." in text


if __name__ == "__main__":
    main()
