"""Additive D1 preparation uses real upload API; no model-quality assertion."""
import json
import os
from pathlib import Path

import httpx
import pytest

from evals.companion import stable_budget as budget, stable_documents as documents
from evals.companion import stable_pdf_repair as repair
from server.services import ingest
from tests.server import test_extract_api as api_tests

# Offline runner behaviour against a current-tree copy of the stable contract;
# the historical contract itself is immutable (see conftest.offline_stable_contract).
pytestmark = pytest.mark.usefixtures("offline_stable_contract")

client = api_tests.client


@pytest.fixture
def original(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "EVIDENCE", tmp_path / "original")
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    budget.initialize()
    documents.freeze("S2-D1")
    return budget.EVIDENCE


async def check_real_response(client):
    result = await repair.prepare(client)
    header, body = result["api_response"]["text"].split("\n\n", 1)
    metadata = json.loads(header.split("\n", 1)[1])
    assert metadata["page_count"] == 3 and metadata["pages_without_native_text"] == [2]
    assert metadata["visual_layout_verified"] is False
    assert metadata["empty_text_is_not_missing_page"] is True
    old = json.loads((budget.EVIDENCE / "S2-D1-preflight.json").read_bytes())
    assert body == old["extracted"]
    assert result["prompt"] == documents.prompt("S2-D1", result["api_response"]["text"])
    assert result["quality_status"] == "not_run" and not result["runner_ready"]
    return result


async def test_real_api_context_and_immutable_original(client, original, tmp_path, monkeypatch):
    before = {p: p.read_bytes() for p in original.rglob("*") if p.is_file()}
    monkeypatch.setattr(budget, "reserve", lambda *a, **kw: pytest.fail("no model reservation"))
    async def no_cleanup(*a, **kw):
        pytest.fail("no model cleanup")
    monkeypatch.setattr(ingest, "_compress", no_cleanup)
    expected = await check_real_response(client)
    output = tmp_path / "additive/d1.json"
    result = await repair.save(client, output)
    assert result["prompt"] == expected["prompt"]
    assert result["authorization"] is None and result["execution_enabled"] is False
    assert {p: p.read_bytes() for p in original.rglob("*") if p.is_file()} == before
    with pytest.raises(FileExistsError):
        await repair.save(client, output)
    with pytest.raises(RuntimeError, match="cannot_write_original"):
        await repair.save(client, original / "new.json")


async def test_network_client_rejected_before_request(original):
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="in_process_api"):
            await repair.prepare(client)


async def test_changed_pdf_refused(client, original):
    (original / "document-inputs/S2-D1/brief.pdf").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="input_changed"):
        await repair.prepare(client)


async def test_ocr_requires_explicit_disabled_scope(client, original, monkeypatch):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: True)
    with pytest.raises(RuntimeError, match="ocr_must_be_disabled"):
        await repair.prepare(client)


@pytest.mark.parametrize("change,error", [
    ("status", "api_failed"), ("truncated", "incomplete"),
    ("chars", "incomplete"), ("empty", "incomplete"), ("inventory", "inventory_missing"),
])
async def test_invalid_api_response_cannot_be_frozen(client, original, monkeypatch, change, error):
    # These intentionally altered responses test only adapter refusal; the
    # successful-path test above exercises the unmodified production endpoint.
    actual = await repair.prepare(client)
    value = dict(actual["api_response"])
    if change == "truncated":
        value["truncated"] = True
    elif change == "chars":
        value["chars"] += 1
    elif change in {"empty", "inventory"}:
        value["text"] = "" if change == "empty" else "plain source without inventory"
        value["chars"] = len(value["text"])

    async def altered(*a, **kw):
        return httpx.Response(400 if change == "status" else 200, json=value)

    monkeypatch.setattr(client, "post", altered)
    with pytest.raises(RuntimeError, match=error):
        await repair.prepare(client)


@pytest.mark.skipif(not os.environ.get("ARSLAN_D1_OFFLINE_PREPARATION"),
                    reason="explicit exclusive offline receipt output required")
async def test_canonical_retained_input_preparation(client, monkeypatch):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    await check_real_response(client)
    await repair.save(client, Path(os.environ["ARSLAN_D1_OFFLINE_PREPARATION"]))
