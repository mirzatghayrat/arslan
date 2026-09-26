"""Manifest integrity only: no network fetch or agent-quality certification."""
import json
import re
from pathlib import Path


def test_public_source_manifest_keeps_versions_and_missing_case_explicit():
    root = Path(__file__).resolve().parents[1]
    pack = json.loads((root / "evals/companion/stage2-public-sources.json").read_text())
    sources = {source["id"]: source for source in pack["sources"]}
    assert len(sources) == len(pack["sources"]) == 5
    assert [case["id"] for case in pack["cases"]] == [f"S2-R{n}" for n in range(1, 5)]
    for source in sources.values():
        assert re.fullmatch(r"[a-f0-9]{40}", source["commit"])
        assert re.fullmatch(r"[a-f0-9]{64}", source["sha256"])
        assert source["path"] in {"README.md", "README.zh-Hans.md"}
        assert source["excerpt_line"] > 0 and source["excerpt"]
    for case in pack["cases"]:
        assert set(case["sources"]) <= sources.keys()
        assert case["review"]
    missing = pack["cases"][1]
    assert missing["state"] == "blocked_inputs_not_selected" and missing["sources"] == []
    assert sources["lightning-current"]["commit"] != sources["lightning-legacy"]["commit"]
    assert sources["opensquilla-en"]["commit"] == sources["opensquilla-zh"]["commit"]
    assert pack["execution"] == {
        "arslan_model_calls": 0, "pilot_outcomes": "not_run", "live_model_configuration": "not_authorized"}
