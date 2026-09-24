import os
import pytest
from evals.companion import stable_release_retest as release

pytestmark = pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_RELEASE") != release.OPT_IN,
                               reason="independent cumulative 60/$6 grant required")


@pytest.mark.parametrize("case", ["S2-R1", "S2-R4"])
async def test_research(case, execution_db, monkeypatch, tmp_path):
    from tests.server.test_stable_research_live import test_stable_research_host
    with release.bound():
        await test_stable_research_host(case, execution_db, monkeypatch, tmp_path)
