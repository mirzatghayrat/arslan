"""One separately approved attempt each; no paid auto-retry."""
import os
import pytest
from evals.companion import stable_two_retest as two

pytestmark = pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_TWO") != two.OPT_IN,
                               reason="independent 12/$1.20 authorization required")


@pytest.mark.parametrize("case", ["S2-R1", "S2-R4"])
async def test_research(case, execution_db, monkeypatch, tmp_path):
    from tests.server.test_stable_research_live import test_stable_research_host
    with two.bound():
        await test_stable_research_host(case, execution_db, monkeypatch, tmp_path)
