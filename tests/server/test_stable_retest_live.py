"""Reuse measured host runners under a separately authorized immutable ledger."""
import os

import pytest

from evals.companion import stable_budget as budget, stable_documents as documents
from evals.companion import stable_pdf_repair as pdf, stable_retest as retest
from server.services import ingest
from tests.server import test_extract_api as api_tests

client = api_tests.client
pytestmark = pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_RETEST") != retest.OPT_IN,
                               reason="additional explicit user grant required")


@pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_RETEST_PREPARE") != "1",
                    reason="explicit offline freeze only")
async def test_freeze_additional_inputs(client, monkeypatch):
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    prepared = await pdf.prepare(client)
    retest.freeze_contract()
    retest.freeze_inputs(prepared["api_response"])
    with retest.bound():
        budget.initialize()
        assert budget.status()["requests"] == 0


@pytest.mark.parametrize("case_id", ["S2-D1", "S2-D3"])
async def test_document_retest(case_id, client, execution_db, monkeypatch, tmp_path):
    from tests.server.test_stable_document_live import test_stable_document_host
    monkeypatch.setattr(ingest.ocr_vision, "is_available", lambda: False)
    if case_id == "S2-D1":
        prepared = await pdf.prepare(client)
        original_read = documents.read_inputs

        def attachment_read(case, bodies):
            if case == "S2-D1":
                assert bodies == documents.inputs(case)
                return prepared["api_response"]["text"]
            return original_read(case, bodies)

        monkeypatch.setattr(documents, "read_inputs", attachment_read)
    with retest.bound():
        await test_stable_document_host(case_id, execution_db, monkeypatch, tmp_path)


async def test_memory_retest(execution_db, monkeypatch, tmp_path):
    from tests.server.test_stable_memory_live import test_stable_memory_host
    with retest.bound():
        await test_stable_memory_host("S2-M2", execution_db, monkeypatch, tmp_path)


@pytest.mark.parametrize("case", ["S2-R1", "S2-R2", "S2-R3", "S2-R4"])
async def test_research_retest(case, execution_db, monkeypatch, tmp_path):
    from tests.server.test_stable_research_live import test_stable_research_host
    with retest.bound():
        await test_stable_research_host(case, execution_db, monkeypatch, tmp_path)
