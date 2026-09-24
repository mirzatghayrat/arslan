"""One explicitly registered attempt per remaining case, never automatic retry."""
import os
import pytest
from evals.companion import stable_four_retest as four

pytestmark = pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_FOUR") != four.OPT_IN,
                               reason="independent 22/$3 grant required")


async def test_document(execution_db, monkeypatch, tmp_path):
    from tests.server.test_stable_document_live import test_stable_document_host
    with four.bound():
        await test_stable_document_host("S2-D3", execution_db, monkeypatch, tmp_path)


async def test_memory(execution_db, monkeypatch, tmp_path):
    from tests.server.test_stable_memory_live import test_stable_memory_host
    with four.bound():
        await test_stable_memory_host("S2-M2", execution_db, monkeypatch, tmp_path)


@pytest.mark.parametrize("case", ["S2-R1", "S2-R4"])
async def test_research(case, execution_db, monkeypatch, tmp_path):
    from tests.server.test_stable_research_live import test_stable_research_host
    with four.bound():
        await test_stable_research_host(case, execution_db, monkeypatch, tmp_path)
