import os

import pytest

from scripts.capability_inventory import ROOT, executor_sources, render


# C5b: the inventory is regenerated in the release PR only, so parallel PRs stop conflicting on it.
# The release workflow diffs it before building; here it is compared only on request. Do not set
# ARSLAN_RELEASE_CHECK in ci.yml: that brings the daily conflicts back.
@pytest.mark.skipif(os.environ.get("ARSLAN_RELEASE_CHECK") != "1",
                    reason="checked at release time only (ARSLAN_RELEASE_CHECK=1; release.yml diffs it)")
def test_generated_inventory_is_current():
    assert (ROOT / "docs/CAPABILITY_INVENTORY.md").read_text() == render()


def test_inventory_tracks_assembled_implementation_without_claiming_grants():
    executors = executor_sources()
    assert executors["run_python"] == "server/registry/executors.py"
    assert executors["read_file"] == "server/registry/file_tools.py"
    assert "patch" not in executors
    assert "Neither grants permission" in render()
