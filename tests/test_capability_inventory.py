from scripts.capability_inventory import ROOT, executor_sources, render


def test_generated_inventory_is_current():
    assert (ROOT / "docs/CAPABILITY_INVENTORY.md").read_text() == render()


def test_inventory_tracks_assembled_implementation_without_claiming_grants():
    executors = executor_sources()
    assert executors["run_python"] == "server/registry/executors.py"
    assert executors["read_file"] == "server/registry/file_tools.py"
    assert "patch" not in executors
    assert "Neither grants permission" in render()
