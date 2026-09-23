"""Real attachment entry-point regression for blank-page completeness claims.

These are offline extraction checks, not a new live D1 attempt or visual audit.
The frozen three-page document and original failed answer remain unchanged.
"""
import json
import hashlib
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from server.services import extract, ingest
from tests.server import test_extract_api as api_tests
from tests.server.test_stage2_inputs import CASES, pdf_bytes
from tests.server.test_pdf_source_locators import mixed_pdf

client = api_tests.client


def inventory(text):
    header, body = text.split("\n\n", 1)
    assert header.startswith("[PDF extraction inventory; not document content]\n")
    return json.loads(header.split("\n", 1)[1]), body


async def test_actual_attachment_keeps_empty_page_in_inventory(client, monkeypatch):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    data = pdf_bytes(CASES["S2-D1"]["pages"])
    response = await client.post("/api/v1/extract", files={"file": ("brief.pdf", data, "application/pdf")})
    assert response.status_code == 200
    result = response.json()
    metadata, body = inventory(result["text"])
    assert metadata["page_count"] == 3
    assert metadata["pages_without_native_text"] == [2]
    assert metadata["page_numbers"] == "one_based_physical_pages"
    assert metadata["visual_layout_verified"] is False
    assert metadata["empty_text_is_not_missing_page"] is True
    assert "not proof of blankness" in metadata["note"]
    assert body == ingest._pdf_text_layer(data).located_text
    assert not result["truncated"]
    if os.environ.get("ARSLAN_STABLE_PDF_EVIDENCE") == "1":
        from evals.companion import stable_budget as budget
        from evals.companion.stable_live import persist
        # Additive offline evidence, never replacing the frozen preflight or
        # failed model answer. Exclusive output creation prevents overwriting.
        persist(budget.EVIDENCE / "pdf-attachment-repair-v1.json", {
            "case": "S2-D1", "environment": "isolated_real_attachment_api_offline",
            "input_sha256": hashlib.sha256(data).hexdigest(), "response": result,
            "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=budget.ROOT, text=True).strip(),
            "extract_source_sha256": hashlib.sha256(Path(extract.__file__).read_bytes()).hexdigest(),
            "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "model_calls": 0, "quality_status": "requires_new_reviewed_model_attempt",
            "native_status": "not_run", "original_failure_preserved": True})


async def test_unread_scan_does_not_become_blank_or_success(client, monkeypatch):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    response = await client.post("/api/v1/extract", files={"file": ("mixed.pdf", mixed_pdf(), "application/pdf")})
    result = response.json()
    metadata, body = inventory(result["text"])
    assert metadata["page_count"] == 4
    assert metadata["pages_without_native_text"] == [2, 3]
    assert result["truncated"]
    assert "[page text not read: unavailable]" in body
    assert '"unread_pages": [2]' in body
    assert "blank_pages" not in metadata


async def test_all_empty_pdf_does_not_turn_metadata_into_source(client, monkeypatch):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    monkeypatch.setattr(ingest, "_ocr_pdf", lambda _: "")
    response = await client.post("/api/v1/extract", files={"file": ("empty.pdf", pdf_bytes(["", ""]), "application/pdf")})
    assert response.status_code == 200
    assert response.json()["text"] == ""
    assert response.json()["chars"] == 0


async def test_inventory_is_bounded_and_source_truncation_remains_visible(monkeypatch, execution_db):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    data = pdf_bytes(["Enough native source text to avoid any OCR."] + [""] * 100)
    metadata, body = inventory((await extract.extract_text(filename="many.pdf", data=data))[0])
    assert metadata["page_count"] == 101
    assert len(metadata["pages_without_native_text"]) == 64
    assert metadata["pages_without_native_text_count"] == 100
    assert metadata["page_list_truncated"] is True
    assert "Enough native source" in body
    monkeypatch.setattr(extract, "settings", SimpleNamespace(attach_extract_char_limit=80))
    text, partial = await extract.extract_text(filename="many.pdf", data=data)
    assert len(text) == 80 and partial


async def test_inventory_cannot_be_rewritten_by_compression(monkeypatch, execution_db):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)

    async def forbidden(_):
        pytest.fail("PDF extraction must not call a cleanup model")

    monkeypatch.setattr(ingest, "_compress", forbidden)
    text, partial = await extract.extract_text(filename="brief.pdf", data=pdf_bytes(CASES["S2-D1"]["pages"]), compress=True)
    metadata, _ = inventory(text)
    assert metadata["page_count"] == 3 and not partial
