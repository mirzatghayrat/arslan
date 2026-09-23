"""Frozen synthetic input boundary checks, never a live pilot completion score."""
import csv
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pytest

from arslan.companion.research import ResearchEvidence, inspect_evidence, receipt
from server.services import extract, ingest
from server.services.input_formats import InputError, read_structured

ROOT = Path(__file__).resolve().parents[2]
PACK = json.loads((ROOT / "evals/companion/stage2-inputs.json").read_text())
CASES = {case["id"]: case for case in PACK["cases"]}


def word_bytes(paragraphs):
    # Fixed ZIP timestamp and stored members keep generated input reproducible.
    body = ''.join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{body}</w:body></w:document>')
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        archive.writestr(ZipInfo("word/document.xml", (2026, 9, 23, 0, 0, 0)), xml)
    return output.getvalue()


def pdf_bytes(pages):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=300, height=300)
        if not text:
            continue
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})})})
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 20 250 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pack_is_twelve_synthetic_cases_and_frozen():
    assert list(CASES) == [f"S2-{group}{n}" for group in "RDM" for n in range(1, 5)]
    assert len(PACK["cases"]) == 12
    assert PACK["environment"] == "synthetic"
    assert PACK["paid_model_calls_authorized"] == 0
    frozen = json.loads((ROOT / "evals/companion/stage2-inputs.freeze.json").read_text())
    assert frozen["revision"] == PACK["revision"]
    assert set(frozen["sha256"]) == {
        "evals/companion/stage2-inputs.json", "tests/server/test_stage2_inputs.py",
        "tests/server/test_memory_multiturn_runtime.py", "tests/server/test_task_repository.py",
        "web/src/__tests__/stage2-input-retention.test.tsx",
    }
    for path, digest in frozen["sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


@pytest.mark.parametrize("case_id", [f"S2-R{n}" for n in range(1, 5)])
def test_research_sources_keep_provenance_without_claiming_quality(case_id):
    case = CASES[case_id]
    trace, claims = [], []
    for index, source in enumerate(case["sources"]):
        value = receipt(source["url"], source["text"], truncated=False)
        trace.append({"tool": "web_extract", "args": {"url": source["url"]}, "result": {
            "ok": True, **source, "source": value.model_dump(mode="json")}})
        claims.append({"id": f"claim-{index}", "kind": "fact", "statement": source["text"],
                       "citations": [{"source_id": value.id, "quote": source["text"]}]})
    report = ResearchEvidence.model_validate({"claims": claims})
    checked = inspect_evidence(report, trace)
    assert checked["read_source_count"] == len(case["sources"])
    assert checked["status"] == "not_run"  # Source admission is NOT answer quality.
    trace[0]["result"]["text"] += " Tampered."
    assert inspect_evidence(report, trace)["status"] == "failed"


def test_pdf_fixed_pages_keep_blank_page_gap_without_model(monkeypatch):
    data = pdf_bytes(CASES["S2-D1"]["pages"])
    assert data == pdf_bytes(CASES["S2-D1"]["pages"])
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    text = ingest._extract_file("brief.pdf", data)
    assert text == (f"[page 1]\n{CASES['S2-D1']['pages'][0]}\n\n"
                    f"[page 3]\n{CASES['S2-D1']['pages'][2]}")


async def test_word_versions_keep_difference_locations():
    case = CASES["S2-D2"]
    for name in ("before", "after"):
        data = word_bytes(case[name])
        assert data == word_bytes(case[name])
        text, truncated = await extract.extract_text(filename=f"{name}.docx", data=data)
        expected = "\n".join(f"[word/document.xml#paragraph={n}] {line}"
                             for n, line in enumerate(case[name], 1))
        assert text == expected and not truncated
    # This oracle defines differences; it is not an agent-produced comparison.
    assert case["before"][1] == case["after"][1]
    assert case["before"][2] == "Deadline: Friday"
    assert case["after"][2] == "Deadline: Monday"
    assert case["after"][4] == "Action: confirm export format"


async def test_csv_preserves_missing_values_currency_and_reopenable_oracle(tmp_path):
    case = CASES["S2-D3"]
    text, truncated = await extract.extract_text(filename="costs.csv", data=case["csv"].encode())
    assert text == case["csv"] and not truncated
    totals, missing = {}, []
    for row_number, row in enumerate(csv.DictReader(io.StringIO(text)), 2):
        if not row["amount"]:
            missing.append(row_number)
            continue
        currency = row["currency"]
        totals[currency] = totals.get(currency, Decimal(0)) + Decimal(row["amount"])
    assert {key: str(value) for key, value in totals.items()} == case["expected_totals"]
    assert missing == case["missing_amount_rows"]
    artifact = tmp_path / "oracle-not-agent-output.csv"
    with artifact.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["currency", "known_total"])
        writer.writerows(sorted(case["expected_totals"].items()))
    with artifact.open(newline="", encoding="utf-8") as stream:
        assert list(csv.DictReader(stream)) == [
            {"currency": "CNY", "known_total": "23.50"}, {"currency": "USD", "known_total": "12.00"}]


def test_unsupported_input_does_not_destroy_independent_valid_input():
    case = CASES["S2-D4"]
    valid = read_structured(case["valid_filename"], case["valid_text"].encode())
    with pytest.raises(InputError, match="^inputs.unsupported$"):
        read_structured(case["unsupported_filename"], case["unsupported_text"].encode())
    assert valid == (case["valid_text"], False)
    assert read_structured(case["valid_filename"], case["valid_text"].encode()) == valid
